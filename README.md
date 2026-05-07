# 🖌️ Scatter Brush Pro - Blender Addon

**Scatter Brush Pro** is a professional Blender tool designed for scattering objects onto surfaces through intuitive painting. It combines **Real-time GPU Previews** with the power of **Geometry Nodes** for an optimized and flexible workflow.

---

## 🚀 Key Features
- **Real-time Painting**: Visual feedback with red path lines and purple preview dots.
- **Optimized Performance**: Uses Geometry Nodes instancing to handle thousands of objects efficiently.
- **Natural Randomization**: Built-in options for random scaling and rotation.
- **One-Click Mesh Conversion**: Fully compatible with the "Apply Modifier" workflow via *Realize Instances*.

---

## 🛠️ Installation

To use this addon permanently in Blender:

1. **Save the script**: Ensure `scatter_brush.py` is saved on your computer.
2. **Open Blender Preferences**: Go to `Edit > Preferences`.
3. **Install**:
    - Navigate to the **Add-ons** tab.
    - Click the **Install...** button at the top right.
    - Select the `scatter_brush.py` file.
4. **Enable**: Find "Scatter Brush Pro" in the list and check the box to enable it.
5. **Save Settings**: Click the ☰ icon (bottom left) and select **Save Preferences** so the addon loads automatically every time you open Blender.

---

## 📖 Usage Guide

The tool is located in the **3D Viewport Sidebar (N key) > Scatter Tab**.

1. **Source Object**: Select the object you want to scatter (e.g., a tree, rock, or grass).
2. **Target Surface**: Select the surface you want to paint on (e.g., a landscape mesh).
3. **Start Painting**: Click the **▶ Start Painting** button.
    - The viewport will automatically align to an orthogonal view for precision.
4. **Controls**:
    - **LMB (Left Mouse Button)**: Hold and drag to paint objects onto the surface.
    - **Enter / Numpad Enter**: Finish painting and generate the final objects.
    - **Esc / Right Click**: Cancel the current stroke or finish the session.

---

## ⚙️ Parameters Explained

| Parameter | Description |
| :--- | :--- |
| **Brush Radius** | The radius of the area where objects will be scattered around your cursor. |
| **Density** | The minimum distance between spawned points. Lower values result in a denser distribution. |
| **Surface Offset** | Adjusts the height of objects relative to the surface (useful for burying roots or floating objects). |
| **Scale Min / Max** | Defines the random scale range for each instance to create a natural look. |
| **Rand Rotation** | The maximum random rotation (in degrees) applied around the Z-axis. |
| **3D Random Rotation** | If enabled, objects will rotate randomly on all three axes (ideal for rocks and debris). |

---

## 💻 Technical Overview (Source Code)

The source code follows standard Blender API patterns for robustness:
- **`ScatterProperties`**: Stores all user-adjustable parameters in the scene.
- **`draw_callback_px`**: Handles the GPU drawing of the red path and purple dots on top of the viewport.
- **`SCATTER_OT_brush`**: A modal operator that manages the painting logic, ray-casting, and point spawning.
- **`_execute_spawn`**: Creates the point-cloud mesh and dynamically builds the Geometry Node tree.
- **`SCATTER_PT_panel`**: Defines the user interface in the Sidebar.

---
*Developed by Truong - 2026*
