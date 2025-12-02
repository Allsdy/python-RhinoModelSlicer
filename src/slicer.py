# -*- coding: utf-8 -*-
import Rhino
import scriptcontext as sc
import rhinoscriptsyntax as rs
import System
import Rhino.UI
import Eto.Forms as forms
import Eto.Drawing as drawing
import subprocess
import os
import re

# ==============================================================================
# 1. 配置 (CONFIGURATION)
# ==============================================================================
SLICER_PATH = "/Applications/OriginalPrusaDrivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"
SLICER_KEY = "Rhino_Slicer_V10_Incremental"

TEMP_DIR = "/tmp" if os.name == 'posix' else "C:\\Temp"
TEMP_STL = os.path.join(TEMP_DIR, "v10_export.stl")
OUTPUT_GCODE = os.path.join(TEMP_DIR, "v10_export.gcode")

# ==============================================================================
# 2. 数据结构
# ==============================================================================
class GCodeLayer:
    def __init__(self, z):
        self.z = z
        self.paths = [] 
        self.total_length = 0.0

    def add_path(self, points):
        if len(points) < 2: return
        self.paths.append(points)
        pl_len = 0
        for i in range(len(points)-1):
            pl_len += points[i].DistanceTo(points[i+1])
        self.total_length += pl_len

# ==============================================================================
# 3. 解析器 (PARSER)
# ==============================================================================
def ParseGCodeAndGetBounds(gcode_path):
    if not os.path.exists(gcode_path) or os.path.getsize(gcode_path) == 0:
        return [], Rhino.Geometry.BoundingBox.Empty

    layers = []
    current_layer = None
    current_path = []
    current_pos = Rhino.Geometry.Point3d(0,0,0)
    last_e = 0.0
    bbox = Rhino.Geometry.BoundingBox.Empty
    
    pattern = re.compile(r"([XYZE])([-+]?[0-9]*\.?[0-9]+)")
    
    with open(gcode_path, 'r') as f:
        for line in f:
            if line.startswith(";") or len(line) < 3: continue
            
            is_g1 = line.startswith("G1")
            is_g0 = line.startswith("G0")
            if not (is_g1 or is_g0): continue

            new_x = current_pos.X
            new_y = current_pos.Y
            new_z = current_pos.Z
            new_e = last_e
            
            matches = pattern.findall(line)
            found_move = False
            found_z_change = False
            
            for axis, val in matches:
                val = float(val)
                if axis == 'X': new_x = val; found_move = True
                if axis == 'Y': new_y = val; found_move = True
                if axis == 'Z': 
                    if abs(val - new_z) > 0.001: found_z_change = True
                    new_z = val; found_move = True
                if axis == 'E': new_e = val

            if not found_move: continue
            target_pos = Rhino.Geometry.Point3d(new_x, new_y, new_z)
            
            if is_g1 and new_e > last_e: bbox.Union(target_pos)
            
            if found_z_change:
                if current_layer and current_path:
                    current_layer.add_path(list(current_path))
                    current_path = []
                current_layer = GCodeLayer(new_z)
                layers.append(current_layer)

            is_extruding = (new_e > last_e)
            
            if is_g1 and is_extruding:
                if not current_layer: 
                    current_layer = GCodeLayer(new_z)
                    layers.append(current_layer)
                if len(current_path) == 0:
                    current_path.append(current_pos)
                current_path.append(target_pos)
            else:
                if current_layer and current_path:
                    current_layer.add_path(list(current_path))
                    current_path = []
            
            current_pos = target_pos
            last_e = new_e
            if "G92" in line and "E0" in line: last_e = 0.0

    if current_layer and current_path:
        current_layer.add_path(current_path)
    return layers, bbox

# ==============================================================================
# 4. 增量几何管理器 (INCREMENTAL GEOMETRY MANAGER)
# ==============================================================================
class IncrementalManager:
    def __init__(self):
        # 存储每层生成的物体ID: { layer_index: [guid, guid...] }
        self.ghost_cache = {} 
        self.active_guids = []
        self.nozzle_id = None
        
        # 记录当前显示的最高Ghost层索引
        self.current_ghost_z = -1
        
        self.align_vec = Rhino.Geometry.Vector3d.Zero
        
        self.layer_red = "Slicer_Active_Red"
        self.layer_gray = "Slicer_Ghost_Gray"
        
        if not rs.IsLayer(self.layer_red): rs.AddLayer(self.layer_red, System.Drawing.Color.Red)
        if not rs.IsLayer(self.layer_gray): rs.AddLayer(self.layer_gray, System.Drawing.Color.FromArgb(80, 80, 80))
        rs.LayerLocked(self.layer_gray, True)

    def SetAlignment(self, vec):
        self.align_vec = vec

    def _ApplyAlign(self, points):
        if self.align_vec.IsZero: return points
        return [p + self.align_vec for p in points]

    def ClearAll(self):
        """完全重置"""
        rs.EnableRedraw(False)
        self._ClearList(self.active_guids)
        if self.nozzle_id: 
            rs.DeleteObject(self.nozzle_id)
            self.nozzle_id = None
        
        # 清除所有缓存的 Ghost
        for idx in self.ghost_cache:
            if self.ghost_cache[idx]:
                rs.DeleteObjects(self.ghost_cache[idx])
        self.ghost_cache = {}
        self.current_ghost_z = -1
        
        rs.EnableRedraw(True)

    def _ClearList(self, guid_list):
        if guid_list:
            rs.DeleteObjects(guid_list)
            del guid_list[:]

    def UpdateDisplay(self, all_layers, target_z_index, progress_pct):
        rs.EnableRedraw(False)
        
        # --- A. 增量处理灰色背景 (Ghost) ---
        # 目标是：让 0 到 target_z_index-1 的层显示出来
        
        needed_max_ghost = target_z_index - 1
        
        # 情况1: 向前拖动 (增加层数)
        if needed_max_ghost > self.current_ghost_z:
            rs.CurrentLayer(self.layer_gray)
            # 只生成新增的层
            for i in range(self.current_ghost_z + 1, needed_max_ghost + 1):
                layer = all_layers[i]
                layer_ids = []
                for path in layer.paths:
                    offset_path = self._ApplyAlign(path)
                    guid = sc.doc.Objects.AddPolyline(offset_path)
                    layer_ids.append(guid)
                self.ghost_cache[i] = layer_ids
            self.current_ghost_z = needed_max_ghost
            
        # 情况2: 向后拖动 (减少层数)
        elif needed_max_ghost < self.current_ghost_z:
            # 删除多余的层
            for i in range(needed_max_ghost + 1, self.current_ghost_z + 1):
                if i in self.ghost_cache:
                    rs.DeleteObjects(self.ghost_cache[i])
                    del self.ghost_cache[i]
            self.current_ghost_z = needed_max_ghost

        # --- B. 处理红色激活层 (Active) ---
        # 这一层总是重新画，因为它受进度条控制，且只有一个，很快
        self._ClearList(self.active_guids)
        if self.nozzle_id: 
            rs.DeleteObject(self.nozzle_id)
            self.nozzle_id = None
            
        rs.CurrentLayer(self.layer_red)
        layer = all_layers[target_z_index]
        target_len = layer.total_length * progress_pct
        acc_len = 0.0
        nozzle_pos = None
        
        for path in layer.paths:
            path_len = 0
            for i in range(len(path)-1):
                path_len += path[i].DistanceTo(path[i+1])
            
            if acc_len + path_len <= target_len:
                offset_path = self._ApplyAlign(path)
                guid = sc.doc.Objects.AddPolyline(offset_path)
                self.active_guids.append(guid)
                acc_len += path_len
                nozzle_pos = offset_path[-1]
            else:
                rem_len = target_len - acc_len
                partial = [path[0]]
                curr = 0
                for i in range(len(path)-1):
                    dist = path[i].DistanceTo(path[i+1])
                    if curr + dist <= rem_len:
                        partial.append(path[i+1])
                        curr += dist
                    else:
                        vec = path[i+1] - path[i]
                        vec.Unitize()
                        end_pt = path[i] + vec * (rem_len - curr)
                        partial.append(end_pt)
                        break
                if len(partial) > 1:
                    offset_partial = self._ApplyAlign(partial)
                    guid = sc.doc.Objects.AddPolyline(offset_partial)
                    self.active_guids.append(guid)
                    nozzle_pos = offset_partial[-1]
                break 

        if nozzle_pos:
            self.nozzle_id = sc.doc.Objects.AddPoint(nozzle_pos)
            obj = sc.doc.Objects.Find(self.nozzle_id)
            obj.Attributes.ObjectColor = System.Drawing.Color.Blue
            obj.Attributes.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
            obj.CommitChanges()

        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()

# ==============================================================================
# 5. UI PANEL
# ==============================================================================
class SlicerPanel(forms.Form):
    def __init__(self):
        self.Title = "Rhino Slicer"
        self.ClientSize = drawing.Size(380, 700)
        self.Topmost = True
        self.Resizable = False
        
        self.geo_manager = IncrementalManager() # 使用增量管理器
        self.layers = []
        self.target_id = None
        self.mesh_bbox = Rhino.Geometry.BoundingBox.Empty
        
        # UI Setup
        self.btn_pick = forms.Button(Text = "1. Pick Mesh/NURBS")
        self.btn_pick.Click += self.OnPick
        
        self.btn_slice = forms.Button(Text = "2. Generate Slice")
        self.btn_slice.Enabled = False
        self.btn_slice.Click += self.OnSlice

        self.btn_toggle = forms.Button(Text = "Show/Hide Model")
        self.btn_toggle.Enabled = False
        self.btn_toggle.Click += self.OnToggleVisibility
        
        # Parameters
        self.num_layer_h = forms.NumericStepper(Value=0.2, MinValue=0.05, MaxValue=1.2, Increment=0.05, DecimalPlaces=2)
        self.num_walls = forms.NumericStepper(Value=2, MinValue=1, MaxValue=10, Increment=1)
        self.num_infill = forms.NumericStepper(Value=15, MinValue=0, MaxValue=100, Increment=5)
        self.combo_infill = forms.DropDown()
        self.combo_infill.DataStore = ["rectilinear", "grid", "triangles", "gyroid", "honeycomb"]
        self.combo_infill.SelectedIndex = 1
        
        self.chk_support = forms.CheckBox(Text = "Generate Support")
        self.combo_support = forms.DropDown()
        self.combo_support.DataStore = ["grid", "snug", "organic"] 
        self.combo_support.SelectedIndex = 0 
        
        self.lbl_status = forms.Label(Text="Status: Ready")
        
        self.lbl_z_info = forms.Label(Text="Z-Level:")
        self.slider_z = forms.Slider(MinValue=0, MaxValue=100, Enabled=False)
        self.slider_z.ValueChanged += self.OnUpdate
        
        self.lbl_p_info = forms.Label(Text="Simulate Path:")
        self.slider_p = forms.Slider(MinValue=0, MaxValue=1000, Value=1000, Enabled=False)
        self.slider_p.ValueChanged += self.OnUpdate
        
        # Layout
        layout = forms.DynamicLayout()
        layout.Padding = drawing.Padding(10)
        layout.Spacing = drawing.Size(5, 5)
        
        layout.AddRow(self.btn_pick)
        layout.AddRow(None)
        
        grp_settings = forms.GroupBox(Text = "Print Settings")
        gl = forms.DynamicLayout()
        gl.Padding = drawing.Padding(5)
        gl.Spacing = drawing.Size(5, 5)
        gl.AddRow("Layer Height (mm):", self.num_layer_h)
        gl.AddRow("Wall Count:", self.num_walls)
        gl.AddRow("Infill Density (%):", self.num_infill)
        gl.AddRow("Infill Pattern:", self.combo_infill)
        gl.AddRow(self.chk_support)
        gl.AddRow("Support Style:", self.combo_support)
        grp_settings.Content = gl
        layout.AddRow(grp_settings)
        
        layout.AddRow(self.btn_slice)
        layout.AddRow(self.btn_toggle)
        layout.AddRow(self.lbl_status)
        
        layout.AddRow(forms.Label(Text="---------------------------------------"))
        layout.AddRow(self.lbl_z_info)
        layout.AddRow(self.slider_z)
        layout.AddRow(self.lbl_p_info)
        layout.AddRow(self.slider_p)
        
        scroll = forms.Scrollable()
        scroll.Content = layout
        self.Content = scroll
        self.Closed += self.OnFormClosed

    def OnPick(self, sender, e):
        self.Visible = False
        try:
            guid = rs.GetObject("Select Mesh or Polysurface", 8 + 16 + 32)
            if guid:
                self.target_id = guid
                obj = sc.doc.Objects.Find(guid)
                self.mesh_bbox = obj.Geometry.GetBoundingBox(True)
                self.lbl_status.Text = "Picked."
                self.lbl_status.TextColor = drawing.Colors.Blue
                self.btn_slice.Enabled = True
                self.btn_toggle.Enabled = True
        except: pass
        self.Visible = True

    def OnToggleVisibility(self, sender, e):
        if not self.target_id: return
        rs.EnableRedraw(False)
        if rs.IsObjectHidden(self.target_id): rs.ShowObject(self.target_id)
        else: rs.HideObject(self.target_id)
        rs.EnableRedraw(True)

    def OnSlice(self, sender, e):
        if not self.target_id: return
        self.lbl_status.Text = "Processing..."
        Rhino.RhinoApp.Wait()
        self.geo_manager.ClearAll()
        
        # 1. Auto-Mesh
        temp_mesh_id = None
        export_id = self.target_id
        obj = sc.doc.Objects.Find(self.target_id)
        if isinstance(obj.Geometry, Rhino.Geometry.Brep):
            self.lbl_status.Text = "Meshing..."
            Rhino.RhinoApp.Wait()
            meshes = Rhino.Geometry.Mesh.CreateFromBrep(obj.Geometry, Rhino.Geometry.MeshingParameters.QualityRenderMesh)
            if meshes:
                joined = Rhino.Geometry.Mesh()
                for m in meshes: joined.Append(m)
                temp_mesh_id = sc.doc.Objects.AddMesh(joined)
                export_id = temp_mesh_id
        
        # 2. Export
        rs.UnselectAllObjects()
        rs.SelectObject(export_id)
        rs.Command('-_Export "{}" _Enter _Enter'.format(TEMP_STL), False)
        rs.UnselectObject(export_id)
        if temp_mesh_id: sc.doc.Objects.Delete(temp_mesh_id, True)
        
        # 3. CLI
        self.lbl_status.Text = "Slicing..."
        Rhino.RhinoApp.Wait()
        
        lh = str(self.num_layer_h.Value)
        walls = str(int(self.num_walls.Value))
        infill_d = str(int(self.num_infill.Value)) + "%"
        infill_p = str(self.combo_infill.SelectedValue)
        
        args = [SLICER_PATH, "--slice", "--export-gcode", "--output", OUTPUT_GCODE, 
                "--layer-height", lh, "--perimeters", walls, 
                "--fill-density", infill_d, "--fill-pattern", infill_p, TEMP_STL]
        
        if self.chk_support.Checked:
            args.append("--support-material")
            args.append("--support-material-style")
            args.append(str(self.combo_support.SelectedValue))

        try:
            res = subprocess.call(args)
            if res != 0:
                self.lbl_status.Text = "Error {}".format(res)
                return
            
            self.layers, gcode_bbox = ParseGCodeAndGetBounds(OUTPUT_GCODE)
            
            if self.layers and gcode_bbox.IsValid:
                rc = self.mesh_bbox.Center
                gc = gcode_bbox.Center
                align_vec = Rhino.Geometry.Vector3d(
                    rc.X - gc.X, rc.Y - gc.Y, self.mesh_bbox.Min.Z - gcode_bbox.Min.Z
                )
                self.geo_manager.SetAlignment(align_vec)

                self.lbl_status.Text = "Done! {} Layers".format(len(self.layers))
                self.lbl_status.TextColor = drawing.Colors.Green
                
                self.slider_z.MaxValue = len(self.layers) - 1
                self.slider_z.Value = 0
                self.slider_z.Enabled = True
                self.slider_p.Enabled = True
                self.slider_p.Value = 1000
                self.OnUpdate(None, None)
            else:
                self.lbl_status.Text = "0 Layers"
        except Exception as ex:
            rs.MessageBox(str(ex))

    def OnUpdate(self, sender, e):
        if not self.layers: return
        idx = int(self.slider_z.Value)
        pct = self.slider_p.Value / 1000.0
        if idx < len(self.layers):
            layer = self.layers[idx]
            real_z = layer.z + self.geo_manager.align_vec.Z
            self.lbl_z_info.Text = "Z-Level: {:.2f}mm (Layer {}/{})".format(real_z, idx+1, len(self.layers))
            self.geo_manager.UpdateDisplay(self.layers, idx, pct)

    def OnFormClosed(self, sender, e):
        self.geo_manager.ClearAll()
        if self.target_id and rs.IsObjectHidden(self.target_id):
             rs.ShowObject(self.target_id)
        if SLICER_KEY in sc.sticky: del sc.sticky[SLICER_KEY]

def Run():
    if SLICER_KEY in sc.sticky:
        try: sc.sticky[SLICER_KEY].Close()
        except: pass
    form = SlicerPanel()
    form.Show()
    sc.sticky[SLICER_KEY] = form

if __name__ == "__main__":
    Run()
    

# ==============================================================================
# 6. PLUGIN ENTRY POINT (插件入口)
# ==============================================================================

# 这是让 Rhino 识别这是一个命令的关键
__commandname__ = "Slicer"

def RunCommand(is_interactive):
    # 1. 防止重复运行 (单例模式)
    if SLICER_KEY in sc.sticky:
        try: 
            sc.sticky[SLICER_KEY].Close()
        except: 
            pass
            
    # 2. 启动面板
    form = SlicerPanel()
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    form.Show()
    
    # 3. 存入内存防止闪退
    sc.sticky[SLICER_KEY] = form
    
    return 0 # 0 = Success

# 如果在编辑器里直接运行，依然有效
if __name__ == "__main__":
    RunCommand(True)