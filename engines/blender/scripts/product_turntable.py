"""Product visualisation: studio set, 3-point lighting, 360° camera orbit.

Params (JSON):
  model_path   optional .glb/.gltf/.obj/.fbx/.stl/.ply – otherwise a primitive is built
  product      bottle | box | can | sphere | torus           (default: bottle)
  color        hex colour of the product                    (default: #2563EB)
  material     glossy | matte | metal | glass | plastic      (default: glossy)
  background   hex colour of the studio                     (default: #F3F4F6)
  frames, fps, resolution [w, h], samples, engine (CYCLES|EEVEE), device (auto|cpu|gpu)
  degrees      orbit angle (default 360), output: frames | still, transparent: bool
"""

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
    set_world,
    studio_lighting,
)


def smooth(obj, bevel=0.0):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    if bevel:
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 4
    obj.select_set(False)


def build_product(kind, material):
    objs = []
    if kind == "box":
        bpy.ops.mesh.primitive_cube_add(size=1.4, location=(0, 0, 0.7))
        objs.append(bpy.context.active_object)
        smooth(objs[-1], bevel=0.06)
    elif kind == "can":
        bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.45, depth=1.4, location=(0, 0, 0.7))
        objs.append(bpy.context.active_object)
        smooth(objs[-1], bevel=0.03)
    elif kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=0.8, location=(0, 0, 0.8))
        objs.append(bpy.context.active_object)
        smooth(objs[-1])
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(major_radius=0.7, minor_radius=0.25, location=(0, 0, 0.25))
        objs.append(bpy.context.active_object)
        smooth(objs[-1])
    else:  # bottle: body + shoulder + neck + cap
        bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.42, depth=1.2, location=(0, 0, 0.6))
        objs.append(bpy.context.active_object)
        smooth(objs[-1], bevel=0.05)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=0.42, location=(0, 0, 1.2))
        shoulder = bpy.context.active_object
        shoulder.scale = (1, 1, 0.55)
        objs.append(shoulder)
        smooth(shoulder)
        bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.14, depth=0.42, location=(0, 0, 1.55))
        objs.append(bpy.context.active_object)
        smooth(objs[-1], bevel=0.02)
        bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.16, depth=0.16, location=(0, 0, 1.8))
        cap = bpy.context.active_object
        smooth(cap, bevel=0.02)
        cap.data.materials.append(make_material("CapMat", "#111827", "matte"))
    for obj in objs:
        if not obj.data.materials:
            obj.data.materials.append(material)
    return objs + ([cap] if kind == "bottle" else [])


def main():
    params = read_params()
    output_dir = params["output_dir"]
    reset_scene()
    set_world(params.get("background", "#F3F4F6"), 0.8)
    configure_render(params, output_dir)
    material = make_material("ProductMat", params.get("color", "#2563EB"), params.get("material", "glossy"))
    if params.get("model_path"):
        objs = import_model(params["model_path"])
        if params.get("override_material"):
            for o in objs:
                if o.type == "MESH":
                    o.data.materials.clear()
                    o.data.materials.append(material)
        normalize_objects(objs, target_size=1.8)
    else:
        build_product(params.get("product", "bottle"), material)
    ground_plane(params.get("background", "#F3F4F6"))
    studio_lighting(1.0)
    frames = int(params.get("frames", 72)) if params.get("output", "frames") != "still" else 1
    orbit_camera(target_z=0.95, distance=float(params.get("camera_distance", 6.8)), height=2.0, frames=frames,
                 degrees=float(params.get("degrees", 360)), lens=float(params.get("lens", 55)))
    bpy.context.scene.frame_end = max(1, frames)
    render(params, output_dir)


if __name__ == "__main__":
    main()
