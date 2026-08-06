import json


def build_layer_report(file_path, reports=[]):
    file = open(file_path)
    layers = json.loads(file.read())
    layer_types = []

    for layer in layers:
        layer_types.append(layer["type"])

        if layer["crs"] == "":
            missing_crs.append(layer["name"])

    counts = {
        layer_type: layer_types.count(layer_type)
        for layer_type in layer_types
    }

    reports.append({
        "total": len(layer_types),
        "types": list(set(layer_types)),
        "missing_crs": missing_crs,
        "counts": counts,
    })
    return reports