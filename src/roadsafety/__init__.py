"""fwh_road_safety — US fatal-crash rate by state, normalised by vehicle-miles.

⚠️ A FATAL-CRASH measure, not a "dangerous roads" measure: NHTSA FARS records
fatal crashes only, and those concentrate on high-speed rural roads while injury
crashes concentrate on urban arterials.

Discovered by the Facetwork runner via the ``facetwork.domains`` entry point::

    [project.entry-points."facetwork.domains"]
    road-safety = "roadsafety:domain"
"""
from __future__ import annotations

from pathlib import Path

from facetwork.domains import DomainPackage

from .handlers import register_all_registry_handlers

domain = DomainPackage(
    name="road-safety",
    ffl_dir=Path(__file__).parent / "ffl",
    register_handlers=register_all_registry_handlers,
)
