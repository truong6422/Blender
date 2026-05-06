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
    "version": (1, 7),
    "blender": (5, 1, 1),
    "location": "View3D > Sidebar > Scatter Tab",
    "description": "Scatter objects with stabilized previews and accurate base alignment",
    "category": "Object",
}

# --- Properties ---
class ScatterProperties(bpy.types.PropertyGroup):
    source_obj: bpy.props.PointerProperty(name="Source Object", type=bpy.types.Object)
    target_surface: bpy.props.PointerProperty(name="Target Surface", type=bpy.types.Object)
    density: bpy.props.FloatProperty(name="Density", default=0.5, min=0.01)
    radius: bpy.props.FloatProperty(name="Brush Radius", default=1.0, min=0.0)
    offset: bpy.props.FloatProperty(name="Surface Offset", default=0.0, description="Offset from surface base")
    merge_with_surface: bpy.props.BoolProperty(name="Merge with Surface", default=True)
    scale_min: bpy.props.FloatProperty(name="Scale Min", default=0.8, min=0.01)
    scale_max: bpy.props.FloatProperty(name="Scale Max", default=1.2, min=0.01)
    random_rotation: bpy.props.FloatProperty(name="Rand Rotation", default=360.0, min=0.0, subtype='ANGLE')
    random_rotation_3d: bpy.props.BoolProperty(name="3D Random Rotation", default=False)

# --- Global Draw Handler ---
def draw_callback_px(self, context):
    if not self._path_points and not self._preview_dots:
        return

    # Use a more robust shader approach for 4.x/5.x
    shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('ALWAYS') # Always on top
    
    # In modern Blender, we can use the matrix stack
    # Or manually bind the MVP matrix
    rv3d = context.region_data
    view_matrix = rv3d.view_matrix
    projection_matrix = rv3d.perspective_matrix
    
    shader.bind()
    try:
        shader.uniform_mat4("ModelViewProjectionMatrix", context.region_data.perspective_matrix)
    except:
        pass
    
    # Draw Path Line (RED)
    if len(self._path_points) > 1:
        try: gpu.state.line_width_set(4.0)
        except: pass
        # Offset points slightly towards camera to avoid z-fighting even with ALWAYS
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": self._path_points})
        shader.uniform_float("color", (1.0, 0.0, 0.0, 1.0))
        batch.draw(shader)

    # Draw Preview Dots (PURPLE)
    if self._preview_dots:
        try: gpu.state.point_size_set(10.0)
        except: pass
        batch_dots = batch_for_shader(shader, 'POINTS', {"pos": self._preview_dots})
        shader.uniform_float("color", (0.7, 0.0, 1.0, 1.0))
        batch_dots.draw(shader)
    
    gpu.state.depth_test_set('LESS')

# --- Operator ---
class SCATTER_OT_brush(bpy.types.Operator):
    """Scatter objects with accurate placement and stable previews"""
    bl_idname = "object.scatter_brush"
    bl_label = "Scatter Brush Pro+"
    bl_options = {'REGISTER', 'UNDO'}

    _handle = None
    _path_points = []
    _preview_dots = []
    _spawn_data = [] 
    _last_path_pos = None
    _painting = False

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
            
        props = context.scene.scatter_props
        
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if not props.target_surface or not props.source_obj:
                    return {'RUNNING_MODAL'}
                
                # Check if clicking outside target
                hit, _, _, _ = self.get_ray_hit(context, event, props.target_surface)
                if not hit:
                    self.cleanup(context)
                    return {'FINISHED'}

                self._painting = True
                self._path_points = []
                self._preview_dots = []
                self._spawn_data = []
                self._last_path_pos = None
                return {'RUNNING_MODAL'}
            
            elif event.value == 'RELEASE':
                self._painting = False
                if self._spawn_data:
                    self.execute_spawn(context, props)
                self._path_points = []
                self._preview_dots = []
                self._spawn_data = []
                return {'RUNNING_MODAL'}

        elif event.type == 'MOUSEMOVE' and self._painting:
            hit, location, normal, _ = self.get_ray_hit(context, event, props.target_surface)
            
            if hit:
                # Offset preview slightly to avoid Z-fighting
                preview_loc = location + normal * 0.01
                
                if not self._path_points or (location - self._path_points[-1]).length > 0.05:
                    self._path_points.append(preview_loc.copy())

                if self._last_path_pos is None or (location - self._last_path_pos).length >= props.density:
                    self.generate_preview(props, location, normal)
                    self._last_path_pos = location

        elif event.type in {'ESC', 'RIGHTMOUSE', 'RET', 'NUMPAD_ENTER'}:
            self.cleanup(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def get_ray_hit(self, context, event, target):
        coord = event.mouse_region_x, event.mouse_region_y
        region = context.region
        rv3d = context.region_data
        vec = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        
        matrix_inv = target.matrix_world.inverted()
        origin_local = matrix_inv @ origin
        vec_local = matrix_inv.to_3x3() @ vec
        
        hit, loc_local, normal_local, _ = target.ray_cast(origin_local, vec_local)
        if hit:
            location = target.matrix_world @ loc_local
            normal = target.matrix_world.to_3x3() @ normal_local
            return True, location, normal, loc_local
        return False, None, None, None

    def cleanup(self, context):
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None

    def generate_preview(self, props, center, normal):
        up = normal.normalized()
        tangent = up.orthogonal().normalized()
        bitangent = up.cross(tangent).normalized()
        
        # Try finding a point on surface within radius
        for _ in range(5): # Multiple attempts to find a point inside boundary
            angle = random.uniform(0, 2 * math.pi)
            r = props.radius * math.sqrt(random.random())
            dot_loc = center + (tangent * r * math.cos(angle)) + (bitangent * r * math.sin(angle))
            
            # Boundary Check: Raycast back to surface
            target = props.target_surface
            matrix_inv = target.matrix_world.inverted()
            # Cast from slightly "above" the point towards the surface
            test_origin = dot_loc + up * 0.1
            test_dir = -up
            
            hit, _, _, _ = target.ray_cast(matrix_inv @ test_origin, matrix_inv.to_3x3() @ test_dir)
            if hit:
                self._preview_dots.append(dot_loc + up * 0.02)
                self._spawn_data.append((dot_loc, up))
                break

    def execute_spawn(self, context, props):
        src = props.source_obj
        target = props.target_surface
        
        # Bounding box in local space to calculate height
        bbox = [mathutils.Vector(v) for v in src.bound_box]
        local_min_z = min(v.z for v in bbox)
        local_max_z = max(v.z for v in bbox)
        
        spawned_objects = []
        
        for loc, up in self._spawn_data:
            new_obj = src.copy()
            new_obj.data = src.data.copy()
            context.collection.objects.link(new_obj)
            
            # Initial orientation
            rot_quat = up.to_track_quat('Z', 'Y')
            new_obj.rotation_mode = 'QUATERNION'
            new_obj.rotation_quaternion = rot_quat
            
            # Apply scale randomization
            scale_factor = random.uniform(props.scale_min, props.scale_max)
            new_obj.scale *= scale_factor
            
            # Logic: Center object at surface hit, then shift up by (origin to bottom) distance
            # If origin is at center, local_min_z is -0.5*height. Shift is +0.5*height.
            # We use local_min_z * final_scale_z to get world-space offset.
            current_scale_z = src.scale.z * scale_factor
            total_shift = (-local_min_z * current_scale_z) + props.offset
            
            new_obj.location = loc + (up * total_shift)
            
            # Randomize Rotation
            if props.random_rotation_3d:
                # Random rotation around all 3 axes
                for axis_idx in range(3):
                    axis = [0, 0, 0]
                    axis[axis_idx] = 1
                    angle = random.uniform(0, props.random_rotation)
                    new_obj.rotation_quaternion = new_obj.rotation_quaternion @ mathutils.Quaternion(axis, angle)
            else:
                # Only Z axis
                rand_rot = random.uniform(0, props.random_rotation)
                new_obj.rotation_quaternion = new_obj.rotation_quaternion @ mathutils.Quaternion((0, 0, 1), rand_rot)
            
            spawned_objects.append(new_obj)
        
        if spawned_objects:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in spawned_objects: obj.select_set(True)
            if props.merge_with_surface:
                target.select_set(True)
                context.view_layer.objects.active = target
            else:
                context.view_layer.objects.active = spawned_objects[0]
            bpy.ops.object.join()

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            props = context.scene.scatter_props
            if not props.target_surface or not props.source_obj:
                self.report({'ERROR'}, "Vui lòng chọn Source Object và Target Surface")
                return {'CANCELLED'}

            # Align view to target surface normal
            self.align_view_to_target(context, props.target_surface)

            self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, (self, context), 'WINDOW', 'POST_VIEW')
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        return {'CANCELLED'}

    def align_view_to_target(self, context, target):
        # Calculate world normal of the target (average normal or Z axis)
        # If it's a plane, its Z world axis is usually the normal
        world_normal = target.matrix_world.to_3x3() @ mathutils.Vector((0, 0, 1))
        
        # Set view rotation to look at the target from normal
        rv3d = context.region_data
        rot = world_normal.to_track_quat('Z', 'Y').inverted()
        rv3d.view_rotation = rot
        
        # Center view on target
        rv3d.view_location = target.matrix_world.to_translation()
        # Set to Orthographic for easier painting
        rv3d.view_perspective = 'ORTHO'

# --- UI Panel ---
class SCATTER_PT_panel(bpy.types.Panel):
    bl_label = "Scatter Brush Pro v1.7"
    bl_idname = "SCATTER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Scatter'

    def draw(self, context):
        layout = self.layout
        props = context.scene.scatter_props
        layout.prop(props, "source_obj")
        layout.prop(props, "target_surface")
        box = layout.box()
        box.label(text="Placement")
        col = box.column(align=True)
        col.prop(props, "radius")
        col.prop(props, "density")
        col.prop(props, "offset", text="Surface Offset")
        col.prop(props, "merge_with_surface")
        box = layout.box()
        box.label(text="Randomness")
        col = box.column(align=True)
        col.prop(props, "scale_min")
        col.prop(props, "scale_max")
        col.prop(props, "random_rotation")
        col.prop(props, "random_rotation_3d")
        layout.separator()
        layout.operator("object.scatter_brush", text="Paint & Merge", icon='BRUSH_DATA')

classes = (ScatterProperties, SCATTER_OT_brush, SCATTER_PT_panel)
def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.scatter_props = bpy.props.PointerProperty(type=ScatterProperties)
def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    del bpy.types.Scene.scatter_props
if __name__ == "__main__":
    register()
