import bpy
import gpu
import random
import mathutils
from bpy_extras import view3d_utils

bl_info = {
    "name": "Scatter Brush",
    "author": "Truong",
    "version": (1, 1),
    "blender": (5, 1, 1),
    "location": "View3D > Sidebar > Scatter Tab",
    "description": "Scatter objects by painting/dragging (Optimized for 5.1.1)",
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
    
    align_to_normal: bpy.props.BoolProperty(
        name="Align to Normal",
        default=True,
        description="Align objects to surface normal"
    )

# --- Operator ---
class SCATTER_OT_brush(bpy.types.Operator):
    """Scatter objects along mouse path"""
    bl_idname = "object.scatter_brush"
    bl_label = "Scatter Brush"
    bl_options = {'REGISTER', 'UNDO'}

    _last_pos = None
    _painting = False

    def modal(self, context, event):
        props = context.scene.scatter_props
        
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._painting = True
                self._last_pos = None
                return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                self._painting = False
                return {'RUNNING_MODAL'}

        elif event.type == 'MOUSEMOVE' and self._painting:
            if not props.source_obj:
                self.report({'WARNING'}, "Please select a Source Object first")
                return {'RUNNING_MODAL'}

            # Get 3D mouse position
            coord = event.mouse_region_x, event.mouse_region_y
            region = context.region
            rv3d = context.region_data
            vec = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            
            # Raycast to find hit point (or use ground plane)
            hit, location, normal, index, object, matrix = context.scene.ray_cast(
                context.view_layer.depsgraph, origin, vec
            )
            
            if not hit:
                # Default to Z=0 plane if no hit
                t = -origin.z / vec.z if vec.z != 0 else 0
                location = origin + vec * t
                normal = mathutils.Vector((0, 0, 1))

            # Check distance for density
            if self._last_pos is None or (location - self._last_pos).length >= props.density:
                self.spawn_object(context, props, location, normal)
                self._last_pos = location

        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def spawn_object(self, context, props, base_loc, normal):
        # Create instance (Linked data for efficiency)
        new_obj = props.source_obj.copy()
        # new_obj.data = props.source_obj.data.copy() # Removed for efficiency, using shared data
        context.collection.objects.link(new_obj)
        
        # Randomize location based on width and thickness
        # We use a tangent space approach if we have a normal
        up = normal
        tangent = up.orthogonal().normalized()
        bitangent = up.cross(tangent).normalized()
        
        offset_w1 = random.uniform(-props.width, props.width)
        offset_w2 = random.uniform(-props.width, props.width)
        offset_t = random.uniform(-props.thickness, props.thickness)
        
        # Position with offsets
        new_obj.location = base_loc + (tangent * offset_w1) + (bitangent * offset_w2) + (up * offset_t)
        
        # Alignment to normal
        if props.align_to_normal:
            rot_quat = up.to_track_quat('Z', 'Y')
            new_obj.rotation_mode = 'QUATERNION'
            new_obj.rotation_quaternion = rot_quat
            
            # Apply random Z rotation in local space
            rand_rot = random.uniform(0, props.random_rotation)
            local_rot = mathutils.Quaternion((0, 0, 1), rand_rot)
            new_obj.rotation_quaternion = new_obj.rotation_quaternion @ local_rot
        else:
            # Default world-up alignment
            rand_rot = random.uniform(0, props.random_rotation)
            new_obj.rotation_euler.z += rand_rot
        
        # Randomize scale
        rand_scale = random.uniform(props.scale_min, props.scale_max)
        new_obj.scale *= rand_scale

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a 3D View")
            return {'CANCELLED'}

# --- UI Panel ---
class SCATTER_PT_panel(bpy.types.Panel):
    bl_label = "Scatter Brush"
    bl_idname = "SCATTER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Scatter'

    def draw(self, context):
        layout = self.layout
        props = context.scene.scatter_props
        
        layout.prop(props, "source_obj")
        
        col = layout.column(align=True)
        col.label(text="Brush Settings:")
        col.prop(props, "density")
        col.prop(props, "width")
        col.prop(props, "thickness")
        
        col.separator()
        col.label(text="Randomization:")
        col.prop(props, "scale_min")
        col.prop(props, "scale_max")
        col.prop(props, "random_rotation")
        col.prop(props, "align_to_normal")
        
        layout.separator()
        layout.operator("object.scatter_brush", text="Start Scattering", icon='BRUSH_DATA')

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
