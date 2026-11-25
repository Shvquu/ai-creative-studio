"""3D logo from an SVG: import curves, extrude + bevel, studio turntable.

Params (JSON):
  svg_path    required – flat SVG logo (paths/shapes)
  color, material, background, extrude (0.08), bevel (0.01) in final scene units (logo is ~2 units wide)
  frames, fps, resolution, samples, engine, device, degrees, output, transparent
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore  # noqa: E402
from acs_common import (  # noqa: E402
    configure_render,
    ground_plane,
    import_model,
    make_material,
    normalize_objects,
    orbit_camera,
    read_params,
    render,
    reset_scene,
    scene_bounds,
    set_world,
    studio_lighting,
)


def main():
    params = read_params()
    output_dir = params["output_dir"]
    svg = params.get("svg_path")
    if not svg or not os.path.isfile(svg):
        raise SystemExit("svg_path missing or not found")
    reset_scene()
    set_world(params.get("background", "#F3F4F6"), 0.8)
    configure_render(params, output_dir)
    objs = [o for o in import_model(svg) if o.type == "CURVE"]
    if not objs:
        raise SystemExit("SVG contained no importable paths")
    style = params.get("material", "glossy")
    single = make_material("LogoMat", params["color"], style) if params.get("color") else None
    # SVGs import at real-world size (often a few cm): scale to ~2 units first so that
    # extrusion/bevel values are meaningful and independent of the SVG's document size.
    bpy.context.view_layer.update()
    mins, maxs = scene_bounds(objs)
    flat_size = max(maxs.x - mins.x, maxs.y - mins.y, 1e-6)
    factor = 2.0 / flat_size
    extrude = float(params.get("extrude", 0.08))
    for layer, obj in enumerate(objs):
        obj.scale = (factor, factor, factor)
        obj.data.extrude = extrude / factor
        obj.data.bevel_depth = float(params.get("bevel", 0.01)) / factor
        obj.data.bevel_resolution = 3
        if single is not None:
            mat = single
        else:  # keep the SVG fill colours, upgraded to a proper shader
            src = obj.data.materials[0] if obj.data.materials else None
            rgb = src.diffuse_color[:3] if src is not None else (0.07, 0.09, 0.15)
            hex_color = "#" + "".join(f"{int(max(0, min(1, c ** (1 / 2.2))) * 255):02X}" for c in rgb)
            mat = make_material(f"LogoMat{layer}", hex_color, style)
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        # SVG lies in the XY plane – stand it up facing the camera; later SVG layers sit
        # slightly in front of earlier ones (avoids z-fighting of stacked shapes).
        obj.rotation_euler = (math.radians(90), 0, 0)
        obj.location.y -= layer * extrude * 0.6
    bpy.context.view_layer.update()
    normalize_objects(objs, target_size=2.0)
    bpy.context.view_layer.update()
    mins, maxs = scene_bounds(objs)
    height = maxs.z - mins.z
    width = maxs.x - mins.x
    distance = float(params.get("camera_distance", 3.2 * max(height, width / 1.78)))
    ground_plane(params.get("background", "#F3F4F6"))
    studio_lighting(1.0)
    frames = int(params.get("frames", 72)) if params.get("output", "frames") != "still" else 1
    orbit_camera(target_z=(mins.z + maxs.z) / 2, distance=distance, height=(mins.z + maxs.z) / 2 + 0.3, frames=frames,
                 degrees=float(params.get("degrees", 40)), lens=50)
    bpy.context.scene.frame_end = max(1, frames)
    render(params, output_dir)


if __name__ == "__main__":
    main()
