import bpy
import gpu
import random
import math
import mathutils
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

bl_info = {
    "name": "Scatter Brush",
    "author": "Truong",
    "version": (2, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Scatter Tab",
    "description": "Scatter objects onto a surface with GPU preview and Geometry Nodes instancing",
    "category": "Object",
}

# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
class ScatterProperties(bpy.types.PropertyGroup):
    source_obj:     bpy.props.PointerProperty(name="Source Object",  type=bpy.types.Object)
    target_surface: bpy.props.PointerProperty(name="Target Surface", type=bpy.types.Object)
    density:        bpy.props.FloatProperty(name="Density",       default=0.5, min=0.01)
    radius:         bpy.props.FloatProperty(name="Brush Radius",  default=1.0, min=0.0)
    offset:         bpy.props.FloatProperty(name="Surface Offset",default=0.0)
    scale_min:      bpy.props.FloatProperty(name="Scale Min",     default=0.8, min=0.01)
    scale_max:      bpy.props.FloatProperty(name="Scale Max",     default=1.2, min=0.01)
    random_rotation:    bpy.props.FloatProperty(name="Rand Rotation (deg)", default=360.0, min=0.0)
    random_rotation_3d: bpy.props.BoolProperty(name="3D Random Rotation",   default=False)


# ---------------------------------------------------------------------------
# GPU Draw Callback  –  runs in POST_PIXEL space (screen pixels, 2-D)
#
# POST_PIXEL is the ONLY reliable way to draw on top of everything in
# modern Blender (4.x / 5.x) without fighting the depth buffer or needing
# a hand-crafted MVP matrix.  We project each 3-D world-space point to
# 2-D screen space with location_3d_to_region_2d() before drawing.
# ---------------------------------------------------------------------------
def draw_callback_px(self, context):
    if not self._path_points and not self._preview_dots:
        return

    region = context.region
    rv3d   = context.region_data
    if not region or not rv3d:
        return

    # 2-D shader (no MVP needed)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    gpu.state.blend_set('ALPHA')

    # --- Draw Path Line (RED) ---
    if len(self._path_points) > 1:
        pts2d = []
        for p in self._path_points:
            co = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
            if co:
                pts2d.append(co)
        if len(pts2d) > 1:
            try:
                gpu.state.line_width_set(3.0)
            except Exception:
                pass
            batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": pts2d})
            shader.uniform_float("color", (1.0, 0.15, 0.15, 1.0))
            batch.draw(shader)

    # --- Draw Preview Dots (PURPLE) ---
    if self._preview_dots:
        dots2d = []
        for p in self._preview_dots:
            co = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
            if co:
                dots2d.append(co)
        if dots2d:
            try:
                gpu.state.point_size_set(10.0)
            except Exception:
                pass
            batch = batch_for_shader(shader, 'POINTS', {"pos": dots2d})
            shader.uniform_float("color", (0.75, 0.1, 1.0, 1.0))
            batch.draw(shader)

    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------
class SCATTER_OT_brush(bpy.types.Operator):
    """Paint-scatter objects onto a surface (Enter / Esc / click outside to finish)"""
    bl_idname = "object.scatter_brush"
    bl_label  = "Scatter Brush Pro v2"
    bl_options = {'REGISTER', 'UNDO'}

    # ---- instance state (NOT class-level lists – those are shared!) --------
    def _reset_stroke(self):
        self._path_points  = []
        self._preview_dots = []
        self._spawn_data   = []
        self._last_pos     = None

    # -----------------------------------------------------------------------
    def invoke(self, context, event):
        if context.space_data.type != 'VIEW_3D':
            return {'CANCELLED'}

        props = context.scene.scatter_props
        if not props.source_obj or not props.target_surface:
            self.report({'ERROR'}, "Please set Source Object and Target Surface first.")
            return {'CANCELLED'}

        # Per-instance state
        self._painting = False
        self._handle   = None
        self._reset_stroke()

        # Align viewport to surface normal (top-down ortho)
        self._align_view(context, props.target_surface)

        # Register draw handler  ← POST_PIXEL (2-D screen space, always on top)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_px, (self, context), 'WINDOW', 'POST_PIXEL'
        )
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # -----------------------------------------------------------------------
    def modal(self, context, event):
        # Force redraw every event so the path animates smoothly
        if context.area:
            context.area.tag_redraw()

        props = context.scene.scatter_props

        # ---- Finish keys --------------------------------------------------
        if event.type in {'ESC', 'RIGHTMOUSE', 'RET', 'NUMPAD_ENTER'}:
            self._finish(context)
            return {'FINISHED'}

        # ---- Left Mouse ---------------------------------------------------
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                hit, _loc, _nrm, _ = self._ray_hit(context, event, props.target_surface)
                if not hit:
                    # Clicked outside surface → stop
                    self._finish(context)
                    return {'FINISHED'}
                self._painting = True
                self._reset_stroke()

            elif event.value == 'RELEASE':
                self._painting = False
                if self._spawn_data:
                    self._execute_spawn(context, props)
                self._reset_stroke()

            return {'RUNNING_MODAL'}

        # ---- Mouse Move ---------------------------------------------------
        if event.type == 'MOUSEMOVE' and self._painting:
            hit, loc, nrm, _ = self._ray_hit(context, event, props.target_surface)
            if hit:
                preview_loc = loc + nrm * 0.05   # lift off surface a bit

                # Append to path (deduplicated by distance)
                if (not self._path_points
                        or (preview_loc - self._path_points[-1]).length > 0.01):
                    self._path_points.append(preview_loc.copy())

                # Spawn point every `density` units
                if (self._last_pos is None
                        or (loc - self._last_pos).length >= props.density):
                    self._add_spawn(props, loc, nrm)
                    self._last_pos = loc.copy()

        return {'RUNNING_MODAL'}

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _finish(self, context):
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None

    def _ray_hit(self, context, event, target):
        coord  = (event.mouse_region_x, event.mouse_region_y)
        region = context.region
        rv3d   = context.region_data
        vec    = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

        m_inv      = target.matrix_world.inverted()
        origin_loc = m_inv @ origin
        vec_loc    = m_inv.to_3x3() @ vec

        hit, loc_l, nrm_l, _ = target.ray_cast(origin_loc, vec_loc)
        if hit:
            loc = target.matrix_world @ loc_l
            nrm = (target.matrix_world.to_3x3() @ nrm_l).normalized()
            return True, loc, nrm, loc_l
        return False, None, None, None

    def _add_spawn(self, props, center, normal):
        up       = normal.normalized()
        tangent  = up.orthogonal().normalized()
        bitan    = up.cross(tangent).normalized()
        target   = props.target_surface
        m_inv    = target.matrix_world.inverted()

        # Up to 5 attempts to land inside the surface boundary
        for _ in range(5):
            angle   = random.uniform(0, 2 * math.pi)
            r       = props.radius * math.sqrt(random.random())
            dot_loc = center + tangent * r * math.cos(angle) + bitan * r * math.sin(angle)

            # Boundary check: cast downward to see if point is still over surface
            test_org = m_inv @ (dot_loc + up * 0.1)
            test_dir = m_inv.to_3x3() @ (-up)
            hit2, _, _, _ = target.ray_cast(test_org, test_dir)
            if hit2:
                self._preview_dots.append(dot_loc + up * 0.02)
                self._spawn_data.append((dot_loc, up))
                break

    def _align_view(self, context, target):
        """Rotate viewport to look straight down onto the target surface."""
        rv3d   = context.region_data
        if not rv3d:
            return
        world_normal = (target.matrix_world.to_3x3() @ mathutils.Vector((0, 0, 1))).normalized()
        rv3d.view_rotation  = world_normal.to_track_quat('Z', 'Y').inverted()
        rv3d.view_location  = target.matrix_world.to_translation()
        rv3d.view_perspective = 'ORTHO'

    # -----------------------------------------------------------------------
    # Spawn  –  Linked Duplicate (giống Alt+D): real objects, shared mesh data
    # -----------------------------------------------------------------------
    def _execute_spawn(self, context, props):
        src    = props.source_obj
        target = props.target_surface

        if not self._spawn_data:
            return

        # Tìm đáy vật thể (điểm Z thấp nhất trong local space)
        bbox        = [mathutils.Vector(v) for v in src.bound_box]
        local_min_z = min(v.z for v in bbox)

        # Empty container để gom nhóm trong Outliner
        container = bpy.data.objects.new(f"Scatter_{src.name}", None)
        container.empty_display_type = 'PLAIN_AXES'
        container.empty_display_size = 0.1
        context.collection.objects.link(container)
        container.parent = target
        container.matrix_parent_inverse = target.matrix_world.inverted()

        for loc, up in self._spawn_data:
            # Linked Duplicate: giống Alt+D
            # copy() sao chép Object nhưng DÙNG CHUNG mesh data với src
            new_obj = src.copy()
            context.collection.objects.link(new_obj)

            # Hướng: Z-axis trùng với pháp tuyến mặt phẳng
            rot_q = up.to_track_quat('Z', 'Y')
            if props.random_rotation_3d:
                for ax_i in range(3):
                    ax = [0, 0, 0]; ax[ax_i] = 1
                    rot_q = rot_q @ mathutils.Quaternion(
                        ax, math.radians(random.uniform(0, props.random_rotation)))
            else:
                rot_q = rot_q @ mathutils.Quaternion(
                    (0, 0, 1), math.radians(random.uniform(0, props.random_rotation)))

            new_obj.rotation_mode       = 'QUATERNION'
            new_obj.rotation_quaternion = rot_q

            # Tỷ lệ ngẫu nhiên
            scale_factor  = random.uniform(props.scale_min, props.scale_max)
            new_obj.scale = src.scale * scale_factor

            # Vị trí: đẩy lên để đáy vật thể chạm mặt phẳng
            shift            = (-local_min_z * src.scale.z * scale_factor) + props.offset
            new_obj.location = loc + up * shift

            # Gom vào container, giữ nguyên world-space
            new_obj.parent = container
            new_obj.matrix_parent_inverse = container.matrix_world.inverted()

        bpy.ops.object.select_all(action='DESELECT')
        container.select_set(True)
        context.view_layer.objects.active = container



# ---------------------------------------------------------------------------
# UI Panel
# ---------------------------------------------------------------------------
class SCATTER_PT_panel(bpy.types.Panel):
    bl_label      = "Scatter Brush Pro v2"
    bl_idname     = "SCATTER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Scatter'

    def draw(self, context):
        layout = self.layout
        props  = context.scene.scatter_props

        layout.prop(props, "source_obj")
        layout.prop(props, "target_surface")

        box = layout.box()
        box.label(text="Placement")
        col = box.column(align=True)
        col.prop(props, "radius")
        col.prop(props, "density")
        col.prop(props, "offset")

        box = layout.box()
        box.label(text="Randomness")
        col = box.column(align=True)
        col.prop(props, "scale_min")
        col.prop(props, "scale_max")
        col.prop(props, "random_rotation")
        col.prop(props, "random_rotation_3d")

        layout.separator()
        layout.operator("object.scatter_brush", text="▶ Start Painting", icon='BRUSH_DATA')


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
classes = (ScatterProperties, SCATTER_OT_brush, SCATTER_PT_panel)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.scatter_props = bpy.props.PointerProperty(type=ScatterProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.scatter_props

if __name__ == "__main__":
    register()
