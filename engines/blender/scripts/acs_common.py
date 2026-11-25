"""Shared helpers for AI Creative Studio Blender scripts (Blender 3.6 – 4.x).

Scripts are executed headless:
    blender --background --factory-startup --python <script>.py -- --params params.json

They print ``ACS_PROGRESS <done> <total>`` lines (parsed by the backend) and write
``result.json`` into the output directory.
"""

import json
import math
import os
import sys

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


def read_params():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--params" not in argv:
        raise SystemExit("missing --params <file.json>")
    with open(argv[argv.index("--params") + 1], encoding="utf-8") as fh:
        return json.load(fh)


def progress(done, total):
    print(f"ACS_PROGRESS {done} {total}", flush=True)


def hex_rgba(value, alpha=1.0):
    v = value.lstrip("#")
    srgb = [int(v[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    # sRGB → linear for Blender colour sockets
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, alpha)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def set_input(node, names, value):
    for name in names:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return True
    return False


def make_material(name, color="#E5E7EB", style="glossy", emission=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    set_input(bsdf, ["Base Color"], hex_rgba(color))
    presets = {
        "matte": {"Metallic": 0.0, "Roughness": 0.8},
        "glossy": {"Metallic": 0.0, "Roughness": 0.25},
        "metal": {"Metallic": 1.0, "Roughness": 0.22},
        "glass": {"Metallic": 0.0, "Roughness": 0.05},
        "plastic": {"Metallic": 0.0, "Roughness": 0.4},
    }
    for key, val in presets.get(style, presets["glossy"]).items():
        set_input(bsdf, [key], val)
    if style == "glass":
        set_input(bsdf, ["Transmission Weight", "Transmission"], 1.0)
        set_input(bsdf, ["IOR"], 1.45)
    if style == "glossy":
        set_input(bsdf, ["Coat Weight", "Clearcoat"], 0.5)
    if emission:
        set_input(bsdf, ["Emission Color", "Emission"], hex_rgba(emission))
        set_input(bsdf, ["Emission Strength"], 2.0)
    return mat


def set_world(color="#F3F4F6", strength=1.0):
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = hex_rgba(color)
    bg.inputs["Strength"].default_value = strength
    return world


def add_area_light(name, location, energy, size, color="#FFFFFF", target=(0, 0, 0.6)):
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.size = size
    data.color = hex_rgba(color)[:3]
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    direction = Vector(target) - Vector(location)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return obj


def studio_lighting(scale=1.0):
    add_area_light("Key", (3.5 * scale, -3.0 * scale, 4.0 * scale), 900 * scale ** 2, 3.0 * scale)
    add_area_light("Fill", (-4.0 * scale, -2.0 * scale, 2.5 * scale), 300 * scale ** 2, 4.0 * scale)
    add_area_light("Rim", (0.0, 4.0 * scale, 3.5 * scale), 600 * scale ** 2, 2.5 * scale)


def ground_plane(color="#F3F4F6", size=40):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "Ground"
    plane.data.materials.append(make_material("GroundMat", color, "matte"))
    return plane


def scene_bounds(objects):
    mins = Vector((math.inf, math.inf, math.inf))
    maxs = Vector((-math.inf, -math.inf, -math.inf))
    found = False
    for obj in objects:
        if obj.type not in {"MESH", "CURVE", "FONT", "SURFACE", "META"}:
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins = Vector(map(min, mins, world))
            maxs = Vector(map(max, maxs, world))
            found = True
    if not found:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    return mins, maxs


def normalize_objects(objects, target_size=2.0, on_ground=True):
    """Scale & move a group of objects so it fits into target_size and stands on z=0."""
    bpy.context.view_layer.update()
    mins, maxs = scene_bounds(objects)
    size = max((maxs - mins).length, 1e-6)
    factor = target_size / size * 1.6
    root = bpy.data.objects.new("ProductRoot", None)
    bpy.context.collection.objects.link(root)
    for obj in objects:
        if obj.parent is None:
            obj.parent = root
    center = (mins + maxs) / 2
    root.scale = (factor, factor, factor)
    root.location = (-center.x * factor, -center.y * factor, (-mins.z * factor) if on_ground else -center.z * factor)
    bpy.context.view_layer.update()
    return root


def orbit_camera(target_z, distance, height, frames, degrees=360.0, lens=50):
    target = bpy.data.objects.new("CamTarget", None)
    bpy.context.collection.objects.link(target)
    target.location = (0, 0, target_z)
    pivot = bpy.data.objects.new("CamPivot", None)
    bpy.context.collection.objects.link(pivot)
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = lens
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.parent = pivot
    cam.location = (0, -distance, height)
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    bpy.context.scene.camera = cam
    if frames > 1 and degrees:
        pivot.rotation_euler = (0, 0, 0)
        pivot.keyframe_insert("rotation_euler", frame=1)
        pivot.rotation_euler = (0, 0, math.radians(degrees) * frames / (frames + 1))
        pivot.keyframe_insert("rotation_euler", frame=frames)
        make_linear(pivot)
    return cam


def make_linear(obj):
    anim = obj.animation_data
    if not anim or not anim.action:
        return
    curves = getattr(anim.action, "fcurves", None)
    if curves is None:  # Blender 5 layered actions
        return
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"


def configure_render(params, output_dir):
    scene = bpy.context.scene
    width, height = params.get("resolution", [1280, 720])
    scene.render.resolution_x = int(width)
    scene.render.resolution_y = int(height)
    scene.render.resolution_percentage = 100
    scene.render.fps = int(params.get("fps", 24))
    scene.frame_start = 1
    scene.frame_end = int(params.get("frames", 72))
    scene.render.film_transparent = bool(params.get("transparent", False))
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA" if scene.render.film_transparent else "RGB"
    engine = params.get("engine", "CYCLES").upper()
    if engine == "EEVEE":
        engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys() else "BLENDER_EEVEE"
    scene.render.engine = engine
    if engine == "CYCLES":
        scene.cycles.samples = int(params.get("samples", 64))
        scene.cycles.use_denoising = bool(params.get("denoise", True))
        try:
            scene.cycles.use_adaptive_sampling = True
        except AttributeError:
            pass
        scene.cycles.device = "CPU"
        if params.get("device", "auto") in ("auto", "gpu"):
            enable_gpu(scene)
    try:
        scene.view_settings.view_transform = params.get("view_transform", "AgX")
    except TypeError:
        scene.view_settings.view_transform = "Filmic"
    os.makedirs(output_dir, exist_ok=True)
    return scene


def enable_gpu(scene):
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return False
    for device_type in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = device_type
        except TypeError:
            continue
        try:
            prefs.get_devices()
        except Exception:
            continue
        devices = [d for d in prefs.devices if d.type == device_type]
        if devices:
            for d in prefs.devices:
                d.use = d.type == device_type
            scene.cycles.device = "GPU"
            print(f"ACS_INFO GPU rendering via {device_type}", flush=True)
            return True
    return False


def _render_still():
    """Render the current frame; fall back to no denoising on builds without OIDN (e.g. distro packages)."""
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as exc:
        scene = bpy.context.scene
        if "denois" in str(exc).lower() and scene.render.engine == "CYCLES" and scene.cycles.use_denoising:
            print("ACS_INFO denoiser unavailable in this Blender build - rendering without denoising", flush=True)
            scene.cycles.use_denoising = False
            bpy.ops.render.render(write_still=True)
        else:
            raise


def render(params, output_dir):
    scene = bpy.context.scene
    files = []
    mode = params.get("output", "frames")
    if mode == "still":
        scene.frame_set(int(params.get("still_frame", 1)))
        path = os.path.join(output_dir, "still.png")
        scene.render.filepath = path
        progress(0, 1)
        _render_still()
        progress(1, 1)
        files.append(path)
    else:
        total = scene.frame_end - scene.frame_start + 1
        for i, frame in enumerate(range(scene.frame_start, scene.frame_end + 1)):
            scene.frame_set(frame)
            path = os.path.join(output_dir, f"frame_{frame:05d}.png")
            scene.render.filepath = path
            _render_still()
            files.append(path)
            progress(i + 1, total)
    result = {"files": files, "mode": mode, "fps": scene.render.fps, "frames": len(files),
              "resolution": [scene.render.resolution_x, scene.render.resolution_y],
              "engine": scene.render.engine, "blender": bpy.app.version_string}
    with open(os.path.join(output_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    if params.get("save_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(output_dir, "scene.blend"))
    return result


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=path)
        else:
            bpy.ops.import_scene.obj(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=path)
        else:
            bpy.ops.import_mesh.stl(filepath=path)
    elif ext == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=path)
        else:
            bpy.ops.import_mesh.ply(filepath=path)
    elif ext == ".svg":
        bpy.ops.import_curve.svg(filepath=path)
    else:
        raise SystemExit(f"unsupported model format: {ext}")
    return [o for o in bpy.data.objects if o not in before]
