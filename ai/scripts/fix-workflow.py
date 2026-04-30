#!/usr/bin/env python3
"""
fix-workflow.py — patches ComfyUI subgraph export bug.

ComfyUI's exporter appends duplicate null inputs to every subgraph instance node.
This script trims them back to only the inputs that have actual link IDs.

Usage:
    python3 fix-workflow.py <input.json> [output.json]

If output.json is omitted, the file is fixed in-place.
"""

import json
import sys


def fix_workflow(data: dict) -> int:
    """
    Trims duplicate null inputs from all subgraph instance nodes.
    Returns the number of nodes fixed.
    """
    subgraphs = data.get("definitions", {}).get("subgraphs", [])
    # Build a map of subgraph id -> number of inputs it declares
    sg_input_count = {sg["id"]: len(sg.get("inputs", [])) for sg in subgraphs}

    fixed_count = 0

    for sg in subgraphs:
        for node in sg.get("nodes", []):
            node_type = node.get("type", "")
            expected = sg_input_count.get(node_type)
            if expected is None:
                continue  # not a subgraph instance node
            inputs = node.get("inputs", [])
            if len(inputs) <= expected:
                continue  # already correct length
            # Keep only the first `expected` inputs, and ensure links are set
            # from whatever non-null links exist in the full list
            link_by_slot = {}
            for i, inp in enumerate(inputs):
                if inp.get("link") is not None:
                    link_by_slot[i % expected] = inp["link"]
            node["inputs"] = inputs[:expected]
            for slot, link_id in link_by_slot.items():
                node["inputs"][slot]["link"] = link_id
            fixed_count += 1

    # Also fix top-level nodes
    for node in data.get("nodes", []):
        node_type = node.get("type", "")
        expected = sg_input_count.get(node_type)
        if expected is None:
            continue
        inputs = node.get("inputs", [])
        if len(inputs) <= expected:
            continue
        link_by_slot = {}
        for i, inp in enumerate(inputs):
            if inp.get("link") is not None:
                link_by_slot[i % expected] = inp["link"]
        node["inputs"] = inputs[:expected]
        for slot, link_id in link_by_slot.items():
            node["inputs"][slot]["link"] = link_id
        fixed_count += 1

    return fixed_count


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else input_path

    with open(input_path) as f:
        data = json.load(f)

    count = fix_workflow(data)

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Fixed {count} node(s). Saved to {output_path}")


if __name__ == "__main__":
    main()
