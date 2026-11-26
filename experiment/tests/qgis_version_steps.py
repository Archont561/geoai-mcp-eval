"""GIS environment version scenarios using simulated host libraries."""

from pytest_bdd import given, then, when

from experiment.services import qgis as qgis_service


@given("a GIS host reporting versions for its desktop and geospatial libraries")
def current_gis_host(fake_current_gis_host: None) -> None:
    """The shared fixture installs a current simulated host."""


@given("a legacy GIS host without some geospatial libraries")
def legacy_gis_host(fake_legacy_gis_host: None) -> None:
    """The shared fixture installs a legacy simulated host."""


@given("a machine without the GIS host libraries")
def no_gis_host(fake_missing_gis_host: None) -> None:
    """The shared fixture makes the host libraries unavailable."""


@when("the researcher requests the GIS environment versions", target_fixture="gis_versions")
def request_gis_versions() -> dict | None:
    return qgis_service.qgis_versions()


@then("the report includes the desktop and all available library versions")
def current_versions_reported(gis_versions: dict) -> None:
    assert gis_versions is not None
    assert gis_versions["qgis"] == "4.2.3-Belém do Pará"
    assert gis_versions["gdal"] == "3.13.3"
    assert gis_versions["geos"] == "3.14.1-CAPI-1.20.5"
    assert gis_versions["proj"] == "9.9.0"
    assert gis_versions["python"]


@then("the report includes the legacy desktop and projection versions")
def legacy_versions_reported(gis_versions: dict) -> None:
    assert gis_versions is not None
    assert gis_versions["qgis"] == "3.40.0"
    assert gis_versions["proj"] == "9.8"


@then("unavailable library versions are marked unknown")
def unavailable_versions_reported(gis_versions: dict) -> None:
    assert gis_versions["gdal"] == "unknown"
    assert gis_versions["geos"] == "unknown"


@then("no GIS version report is available")
def no_gis_version_report(gis_versions: dict | None) -> None:
    assert gis_versions is None
