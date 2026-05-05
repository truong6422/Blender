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
    "version": (1, 5),
    "blender": (5, 1, 1),
    "location": "View3D > Sidebar > Scatter Tab",
    "description": "Optimized Scatter with Preview and Auto-Merge",
    "category": "Object",
}

# --- Properties ---
class ScatterProperties(bpy.types.PropertyGroup):
    source_obj: bpy.props.PointerProperty(
        name="Source Object",
        type=bpy.types.Object,
        description="Object to be scattered"
    )
    
    target_surface: bpy.props.PointerProperty(
        name="Target Surface",
        type=bpy.types.Object,
        description="The plane/object to paint on"
    )
    
    density: bpy.props.FloatProperty(
        name="Density", default=0.5, min=0.01
    )
    
    radius: bpy.props.FloatProperty(
        name="Brush Radius", default=1.0, min=0.0
    )
    
    offset: bpy.props.FloatProperty(
        name="Surface Offset", default=0.0,
        description="Extra offset from surface base"
    )
    
    auto_join: bpy.props.BoolProperty(
        name="Merge Results",
        default=True,
        description="Merge all scattered objects into one mesh to save performance"
    )
    
    scale_min: bpy.props.FloatProperty(name="Scale Min", default=0.8, min=0.01)
    scale_max: bpy.props.FloatProperty(name="Scale Max", default=1.2, min=0.01)
    random_rotation: bpy.props.FloatProperty(name="Rand Rotation", default=360.0, min=0.0, subtype='ANGLE')

# --- Global Draw Handler ---
def draw_callback_px(self, context):
    if not self._path_points and not self._preview_dots:
        return

    shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE') # Make sure previews are visible on top of everything
    
    # Path Line (RED)
    if len(self._path_points) > 1:
        gpu.state.line_width_set(4.0)
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": self._path_points})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.0, 0.0, 1.0))
        batch.draw(shader)

    # Preview Dots (PURPLE)
    if self._preview_dots:
        gpu.state.point_size_set(8.0)
        batch_dots = batch_for_shader(shader, 'POINTS', {"pos": self._preview_dots})
        shader.bind()
        shader.uniform_float("color", (0.7, 0.0, 1.0, 1.0))
        batch_dots.draw(shader)
    
    gpu.state.depth_test_set('LESS') # Restore default

# --- Operator ---
class SCATTER_OT_brush(bpy.types.Operator):
    """Scatter with base-alignment and auto-merge optimization"""
    bl_idname = "object.scatter_brush"
    bl_label = "Scatter Brush Pro"
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
                    self.report({'WARNING'}, "Source and Target objects must be set")
                    return {'RUNNING_MODAL'}
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
            # Raycast logic
            coord = event.mouse_region_x, event.mouse_region_y
            region = context.region
            rv3d = context.region_data
            vec = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            
            target = props.target_surface
            matrix_inv = target.matrix_world.inverted()
            origin_local = matrix_inv @ origin
            vec_local = matrix_inv.to_3x3() @ vec
            
            hit, loc_local, normal_local, index = target.ray_cast(origin_local, vec_local)
            
            if hit:
                location = target.matrix_world @ loc_local
                normal = target.matrix_world.to_3x3() @ normal_local
                
                if not self._path_points or (location - self._path_points[-1]).length > 0.05:
                    self._path_points.append(location.copy())

                if self._last_path_pos is None or (location - self._last_path_pos).length >= props.density:
                    self.generate_preview(props, location, normal)
                    self._last_path_pos = location

        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def generate_preview(self, props, center, normal):
        up = normal.normalized()
        tangent = up.orthogonal().normalized()
        bitangent = up.cross(tangent).normalized()
        
        angle = random.uniform(0, 2 * math.pi)
        r = props.radius * math.sqrt(random.random())
        
        # Calculate base offset to keep obj on surface
        # We'll calculate the bounding box shift in execute_spawn, but here we just show the base loc
        dot_loc = center + (tangent * r * math.cos(angle)) + (bitangent * r * math.sin(angle))
        
        self._preview_dots.append(dot_loc)
        self._spawn_data.append((dot_loc, up))

    def execute_spawn(self, context, props):
        # Calculate source object height offset (to sit on base)
        src = props.source_obj
        # Find the lowest Z point in local space
        min_z = min((mathutils.Vector(b).z for b in src.bound_box))
        
        spawned_objects = []
        
        for loc, up in self._spawn_data:
            new_obj = src.copy()
            new_obj.data = src.data.copy() # Independent copy to allow joining without affecting source
            context.collection.objects.link(new_obj)
            
            # Position alignment
            new_obj.location = loc
            
            # Rotation alignment
            rot_quat = up.to_track_quat('Z', 'Y')
            new_obj.rotation_mode = 'QUATERNION'
            new_obj.rotation_quaternion = rot_quat
            
            # Apply local Z offset so base touches surface
            # Note: min_z is local. We need to shift along the local Z axis of the new object
            # After track_quat, local Z is 'up'
            shift = -min_z + props.offset
            new_obj.location += up * shift
            
            # Randomness
            rand_rot = random.uniform(0, props.random_rotation)
            new_obj.rotation_quaternion = new_obj.rotation_quaternion @ mathutils.Quaternion((0, 0, 1), rand_rot)
            new_obj.scale *= random.uniform(props.scale_min, props.scale_max)
            
            spawned_objects.append(new_obj)
        
        # Optimization: Join all into one object
        if props.auto_join and len(spawned_objects) > 0:
            # Deselect all
            bpy.ops.object.select_all(action='DESELECT')
            for obj in spawned_objects:
                obj.select_set(True)
            context.view_layer.objects.active = spawned_objects[0]
            bpy.ops.object.join()
            context.active_object.name = f"Scatter_Result_{src.name}"

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, (self, context), 'WINDOW', 'POST_VIEW')
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        return {'CANCELLED'}

# --- UI Panel ---
class SCATTER_PT_panel(bpy.types.Panel):
    bl_label = "Scatter Brush (Optimized)"
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
        col.prop(props, "offset", text="Base Offset")
        col.prop(props, "auto_join")
        
        box = layout.box()
        box.label(text="Randomness")
        col = box.column(align=True)
        col.prop(props, "scale_min")
        col.prop(props, "scale_max")
        col.prop(props, "random_rotation")
        
        layout.separator()
        layout.operator("object.scatter_brush", text="Paint & Merge", icon='BRUSH_DATA')

# --- Registration ---
classes = (ScatterProperties, SCATTER_OT_brush, SCATTER_PT_panel)

def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.scatter_props = bpy.props.PointerProperty(type=ScatterProperties)

def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    del bpy.types.Scene.scatter_props

if __name__ == "__main__":
    register()
