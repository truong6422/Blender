import bpy
import gpu
import random
import mathutils
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

bl_info = {
    "name": "Scatter Brush",
    "author": "Truong",
    "version": (1, 2),
    "blender": (5, 1, 1),
    "location": "View3D > Sidebar > Scatter Tab",
    "description": "Scatter objects with path preview and delayed spawning",
    "category": "Object",
}

# --- Properties ---
class ScatterProperties(bpy.types.PropertyGroup):
    source_obj: bpy.props.PointerProperty(
        name="Source Object",
        type=bpy.types.Object,
        description="Object to be scattered"
    )
    
    density: bpy.props.FloatProperty(
        name="Density",
        default=0.5,
        min=0.01,
        description="Distance between spawned objects"
    )
    
    width: bpy.props.FloatProperty(
        name="Width",
        default=1.0,
        min=0.0,
        description="Random spread width"
    )
    
    thickness: bpy.props.FloatProperty(
        name="Thickness",
        default=0.2,
        min=0.0,
        description="Random vertical offset"
    )
    
    scale_min: bpy.props.FloatProperty(
        name="Scale Min",
        default=0.8,
        min=0.01
    )
    
    scale_max: bpy.props.FloatProperty(
        name="Scale Max",
        default=1.2,
        min=0.01
    )
    
    random_rotation: bpy.props.FloatProperty(
        name="Rand Rotation",
        default=360.0,
        min=0.0,
        max=360.0,
        subtype='ANGLE'
    )

# --- Global Draw Handler ---
def draw_callback_px(self, context):
    if not self._path_points and not self._preview_dots:
        return

    shader = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR') if hasattr(gpu.shader, 'from_builtin') else None
    # For newer Blender, use 3D_POLYLINE or 3D_UNIFORM_COLOR
    shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
    
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2.0)
    
    # Draw Path Line
    if len(self._path_points) > 1:
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": self._path_points})
        shader.bind()
        shader.uniform_float("color", (0.0, 0.5, 1.0, 0.8)) # Blue path
        batch.draw(shader)

    # Draw Preview Dots
    if self._preview_dots:
        batch_dots = batch_for_shader(shader, 'POINTS', {"pos": self._preview_dots})
        gpu.state.point_size_set(5.0)
        shader.bind()
        shader.uniform_float("color", (1.0, 1.0, 0.0, 1.0)) # Yellow dots
        batch_dots.draw(shader)

# --- Operator ---
class SCATTER_OT_brush(bpy.types.Operator):
    """Scatter objects along mouse path with preview"""
    bl_idname = "object.scatter_brush"
    bl_label = "Scatter Brush"
    bl_options = {'REGISTER', 'UNDO'}

    _handle = None
    _path_points = []
    _preview_dots = []
    _spawn_data = [] # List of (location, normal)
    _last_path_pos = None
    _painting = False

    def modal(self, context, event):
        context.area.tag_redraw()
        props = context.scene.scatter_props
        
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._painting = True
                self._path_points = []
                self._preview_dots = []
                self._spawn_data = []
                self._last_path_pos = None
                return {'RUNNING_MODAL'}
            
            elif event.value == 'RELEASE':
                self._painting = False
                if not props.source_obj:
                    self.report({'WARNING'}, "Source Object missing")
                else:
                    self.execute_spawn(context, props)
                
                # Reset previews after spawn
                self._path_points = []
                self._preview_dots = []
                self._spawn_data = []
                return {'RUNNING_MODAL'}

        elif event.type == 'MOUSEMOVE' and self._painting:
            coord = event.mouse_region_x, event.mouse_region_y
            region = context.region
            rv3d = context.region_data
            vec = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            
            # Draw on XY Plane (Z=0) as requested
            if vec.z != 0:
                t = -origin.z / vec.z
                location = origin + vec * t
            else:
                location = origin
            
            # Add to path preview
            if not self._path_points or (location - self._path_points[-1]).length > 0.1:
                self._path_points.append(location.copy())

            # Check distance for density and generate dots
            if self._last_path_pos is None or (location - self._last_path_pos).length >= props.density:
                self.generate_preview_point(props, location)
                self._last_path_pos = location

        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def generate_preview_point(self, props, base_loc):
        # We assume drawing on XY plane, so normal is Up
        normal = mathutils.Vector((0, 0, 1))
        
        # Randomize location preview
        offset_x = random.uniform(-props.width, props.width)
        offset_y = random.uniform(-props.width, props.width)
        offset_z = random.uniform(-props.thickness, props.thickness)
        
        dot_loc = base_loc + mathutils.Vector((offset_x, offset_y, offset_z))
        
        self._preview_dots.append(dot_loc)
        self._spawn_data.append((dot_loc, normal))

    def execute_spawn(self, context, props):
        for loc, norm in self._spawn_data:
            new_obj = props.source_obj.copy()
            context.collection.objects.link(new_obj)
            
            new_obj.location = loc
            
            # Random rotation
            rand_rot = random.uniform(0, props.random_rotation)
            new_obj.rotation_euler.z = rand_rot
            
            # Random scale
            rand_scale = random.uniform(props.scale_min, props.scale_max)
            new_obj.scale *= rand_scale

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, (self, context), 'WINDOW', 'POST_VIEW')
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a 3D View")
            return {'CANCELLED'}

# --- UI Panel ---
class SCATTER_PT_panel(bpy.types.Panel):
    bl_label = "Scatter Brush (Pro)"
    bl_idname = "SCATTER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Scatter'

    def draw(self, context):
        layout = self.layout
        props = context.scene.scatter_props
        
        layout.prop(props, "source_obj")
        
        box = layout.box()
        box.label(text="Plane Settings (Z=0)")
        col = box.column(align=True)
        col.prop(props, "density")
        col.prop(props, "width")
        col.prop(props, "thickness")
        
        box = layout.box()
        box.label(text="Randomization")
        col = box.column(align=True)
        col.prop(props, "scale_min")
        col.prop(props, "scale_max")
        col.prop(props, "random_rotation")
        
        layout.separator()
        layout.operator("object.scatter_brush", text="Start Painting", icon='BRUSH_DATA')

# --- Registration ---
classes = (
    ScatterProperties,
    SCATTER_OT_brush,
    SCATTER_PT_panel,
)

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
