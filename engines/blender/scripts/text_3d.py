"""Animated 3D typography (titles, intros, logos as text).

Params (JSON):
  text        string (\\n for line breaks)
  font_path   optional .ttf/.otf (default: Blender's built-in font)
  color, material, background, accent (light colour)
  extrude (0.12), bevel (0.02)
  animation   rise | spin | zoom | none
  frames, fps, resolution, samples, engine, device, output, transparent
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore  # noqa: E402
from acs_common import (  # noqa: E402
    add_area_light,
    configure_render,
    make_linear,
    make_material,
    read_params,
    render,
    reset_scene,
    scene_bounds,
    set_world,
)


def main():
    params = read_params()
    output_dir = params["output_dir"]
    reset_scene()
    set_world(params.get("background", "#0F172A"), 0.6)
    configure_render(params, output_dir)
    frames = int(params.get("frames", 72)) if params.get("output", "frames") != "still" else 1

    bpy.ops.object.text_add(location=(0, 0, 0))
    txt = bpy.context.active_object
    txt.data.body = params.get("text", "AI Creative Studio").replace("\\n", "\n")
    txt.data.align_x = "CENTER"
    txt.data.align_y = "CENTER"
    txt.data.extrude = float(params.get("extrude", 0.12))
    txt.data.bevel_depth = float(params.get("bevel", 0.02))
    txt.data.bevel_resolution = 3
    if params.get("font_path") and os.path.isfile(params["font_path"]):
        txt.data.font = bpy.data.fonts.load(params["font_path"])
    txt.rotation_euler = (math.radians(90), 0, 0)
    txt.data.materials.append(make_material("TextMat", params.get("color", "#F8FAFC"), params.get("material", "metal")))

    bpy.context.view_layer.update()
    mins, maxs = scene_bounds([txt])
    width = max(maxs.x - mins.x, 1e-3)
    height = max(maxs.z - mins.z, 1e-3)
    fit = 3.2 / max(width, height * 1.8)
    txt.scale = (fit, fit, fit)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 50
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (0, -6, 0.2)
    cam.rotation_euler = (math.radians(88), 0, 0)
    bpy.context.scene.camera = cam

    accent = params.get("accent", "#38BDF8")
    add_area_light("Key", (3, -4, 3), 700, 3)
    add_area_light("Accent", (-3.5, -1, -1.5), 500, 2.5, color=accent, target=(0, 0, 0))
    add_area_light("Rim", (0, 3, 2), 900, 3)

    anim = params.get("animation", "rise")
    if frames > 1 and anim != "none":
        settle = max(2, int(frames * 0.6))
        if anim == "rise":
            txt.location = (0, 0, -1.2)
            txt.rotation_euler = (math.radians(60), 0, 0)
            txt.keyframe_insert("location", frame=1)
            txt.keyframe_insert("rotation_euler", frame=1)
            txt.location = (0, 0, 0)
            txt.rotation_euler = (math.radians(90), 0, 0)
            txt.keyframe_insert("location", frame=settle)
            txt.keyframe_insert("rotation_euler", frame=settle)
        elif anim == "spin":
            txt.rotation_euler = (math.radians(90), 0, math.radians(-90))
            txt.keyframe_insert("rotation_euler", frame=1)
            txt.rotation_euler = (math.radians(90), 0, 0)
            txt.keyframe_insert("rotation_euler", frame=settle)
        elif anim == "zoom":
            cam.location = (0, -14, 0.2)
            cam.keyframe_insert("location", frame=1)
            cam.location = (0, -6, 0.2)
            cam.keyframe_insert("location", frame=frames)
            make_linear(cam)
    bpy.context.scene.frame_end = max(1, frames)
    render(params, output_dir)


if __name__ == "__main__":
    main()
