# Rhino Model Slicer
A lightweight, real-time 3D slicing and G-code preview tool integrated directly into Rhino 7/8.


https://github.com/user-attachments/assets/b06936bd-e15f-4dcb-aef1-2f989883abea



#### 📖 Overview
Rhino Slicer bridges the gap between CAD design and Additive Manufacturing. Instead of constantly exporting STLs, opening a slicer software, and checking for errors, this tool allows you to visualize the physical toolpath (G-code) directly inside the Rhino viewport.

It leverages the robust slicing engine of PrusaSlicer in the background to generate accurate, printable paths, while providing a seamless UI within Rhino.

#### ✨ Key Features
Visualization: View slice layers and toolpaths inside the Rhino model space.

Auto-Mesh Conversion: Works directly on NURBS (Polysurfaces/Breps) by auto-meshing in the background. No need to manually mesh your objects.

Smart Alignment: Automatically aligns the G-code preview with your original model, even if the object is floating or off-center.

Incremental Rendering: Optimized engine that handles high-layer-count models without freezing the interface.

Dual-Color Display: Distinguishes between Model Geometry (Red) and Support Material (Cyan).

Full Control:

Adjust Layer Height, Wall Count, and Infill Density.

Toggle Support Generation (Grid, Snug, Organic/Tree).

Z-Level Slider: Inspect specific layers.

Path Simulator: Animate the nozzle movement for the active layer.

#### ⚙️ Prerequisites
Rhino 7 or Rhino 8 (macOS or Windows).

PrusaSlicer (Required as the backend engine).

Download here: PrusaSlicer Downloads

Note: Even if you use a Bambu Lab printer, PrusaSlicer is required for this plugin to generate the preview geometry reliably.

#### 🚀 Installation & Setup
1. Download the Script
Save the Python script (e.g., RhinoSlicer.py) to a safe location on your computer. (e.g., /Users/YourName/Scripts/RhinoSlicer.py)

2. Configure the Slicer Path (Crucial!)
Open the script in a text editor (or Rhino's EditPythonScript) and look for the configuration section at the top. You must set the SLICER_PATH to match your PrusaSlicer installation.

For macOS Users:

Python

### Default location for PrusaSlicer on Mac
SLICER_PATH = "/Applications/OriginalPrusaDrivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"
For Windows Users:

Python

### Default location for PrusaSlicer on Windows
SLICER_PATH = r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe"
3. Running the Tool
You can run the tool using one of two methods:

Method A (Direct Run): Type EditPythonScript in Rhino, open the file, and click the Play button.

Method B (Create Alias - Recommended):

Go to Rhino Preferences > Aliases.

Add a new alias (e.g., Slicer).

Set the command macro: ! _-RunPythonScript "/Path/To/Your/RhinoSlicer.py"

Now you can simply type Slicer in the command line.

#### 🎮 How to Use
Launch: Run the script to open the Rhino Slicer Pro panel.

Pick Object: Click 1. Pick Mesh/NURBS and select your 3D model in the viewport.

Tip: The tool auto-detects NURBS objects and converts them to high-quality meshes automatically.

Configure Settings:

Set your desired Layer Height (e.g., 0.2mm).

Adjust Wall Count and Infill %.

Check Generate Support if your model has overhangs.

Generate: Click 2. Generate Slice.

Status: Wait for the status text to turn Green ("Success").

Visualize:

Z-Level Slider: Drag up and down to scan through the height of the model.

Path Slider: Drag left and right to simulate the print head movement for the current layer.

Toggle Visibility: Use the button to hide your original Rhino model to see the internal infill and support structures clearly.

🔧 Troubleshooting
"Slicer Failed / Error Code 127":

This usually means the SLICER_PATH in the code is incorrect. Check where PrusaSlicer is installed on your Mac/PC.

"Error: 0 Layers":

The object might be too small (check your units, ensure the model is in mm).

The object might be non-manifold (open edges).

Support not showing:

Ensure "Generate Support" is checked.

Try changing the support type to "Grid" or "Organic".

The overhang might not be steep enough to trigger support generation (threshold is set to 45°).
