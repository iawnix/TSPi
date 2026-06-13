"""Endpoint loading, image-set construction, and image IO for NEB.

Wraps the small set of ASE image operations the driver and external-Gaussian
continuation paths share: load reactant/product, interpolate an image set,
write image directories and trajectories, and read an existing image directory
back as ASE atoms.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from transition_state_workflow.tool.ase_neb.errors import ConfigError
from transition_state_workflow.tool.ase_neb.gaussian_calc import import_ase_bits


def load_endpoint_images(cfg: dict[str, Any]) -> tuple[Any, Any]:
    bits = import_ase_bits()
    read = bits["read"]
    reactant = read(cfg["reactant"])
    product = read(cfg["product"])
    r_symbols = reactant.get_chemical_symbols()
    p_symbols = product.get_chemical_symbols()
    if r_symbols != p_symbols:
        raise ConfigError(
            "reactant/product atom order mismatch; map atoms first before running NEB"
        )
    return reactant, product


def build_images_from_endpoints(cfg: dict[str, Any], reactant: Any, product: Any) -> list[Any]:
    bits = import_ase_bits()
    images = [reactant]
    images.extend(reactant.copy() for _ in range(cfg["images"] - 2))
    images.append(product)

    neb_cls = bits["NEB"]
    neb = neb_cls(images)
    if cfg["interpolation"] == "idpp":
        neb.interpolate(method="idpp")
    else:
        neb.interpolate()
    return images


def build_images(cfg: dict[str, Any]) -> list[Any]:
    reactant, product = load_endpoint_images(cfg)
    return build_images_from_endpoints(cfg, reactant, product)


def write_image_set(images: list[Any], node_dir: Path, prefix: str) -> None:
    bits = import_ase_bits()
    write = bits["write"]
    image_dir = node_dir / "images"
    traj_dir = node_dir / "trajectories"
    image_dir.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)
    for index, image in enumerate(images):
        write(image_dir / f"{prefix}_image_{index:02d}.xyz", image)
    write(traj_dir / f"{prefix}_path.xyz", images)


def natural_path_key(path: Path) -> list[Any]:
    key: list[Any] = []
    for part in re.split(r"(\d+)", path.name):
        key.append(int(part) if part.isdigit() else part.lower())
    return key


def check_image_consistency(images: list[Any], files: list[Path]) -> None:
    if len(images) < 2:
        raise ConfigError("NEB continuation needs at least two images")
    ref_symbols = images[0].get_chemical_symbols()
    ref_n = len(images[0])
    for index, image in enumerate(images):
        if len(image) != ref_n:
            raise ConfigError(
                f"image atom count mismatch at {files[index]}: "
                f"{len(image)} != {ref_n}"
            )
        if image.get_chemical_symbols() != ref_symbols:
            raise ConfigError(
                f"image element/order mismatch at {files[index]}; "
                "all images must use identical atom order"
            )


def read_xyz_images_from_dir(xyz_dir: Path, pattern: str, *, index: Any = 0) -> tuple[list[Any], list[Path]]:
    bits = import_ase_bits()
    read = bits["read"]
    if not xyz_dir.is_dir():
        raise ConfigError(f"xyz image directory not found: {xyz_dir}")
    files = sorted(xyz_dir.glob(pattern), key=natural_path_key)
    if len(files) < 2:
        raise ConfigError(f"need at least 2 xyz images in {xyz_dir} matching {pattern}")
    images = [read(path, index=index) for path in files]
    check_image_consistency(images, files)
    return images, files


__all__ = [
    "load_endpoint_images",
    "build_images_from_endpoints",
    "build_images",
    "write_image_set",
    "natural_path_key",
    "check_image_consistency",
    "read_xyz_images_from_dir",
]
