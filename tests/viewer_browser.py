"""Browser smoke test against a running plugin installation with a published local ENC.

Run with Playwright and Chromium installed. Select a layer covering a small chart
area so fitting its extent reaches the viewer's search scale.
"""
import argparse
import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


def check(base, layer, chromium=None):
    root = urlsplit(base)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chromium)
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def local_only(route):
            address = urlsplit(route.request.url)
            if (address.scheme, address.netloc) == (root.scheme, root.netloc):
                route.continue_()
            else:
                errors.append(route.request.url)
                route.abort()

        page.route("**/*", local_only)
        page.goto(base.rstrip("/") + "/enc/viewer/index.html")
        expect(page.get_by_role("heading", name="ENC viewer and search demo")).to_be_visible()
        page.get_by_role("button", name="Layers", exact=True).click()
        chart = page.locator("#chart")
        if chart.is_enabled():
            chart.select_option("")
        for enabled in page.locator("#layers input:checked").all():
            enabled.uncheck()
        page.get_by_label("Filter layers").fill(layer)
        row = page.get_by_role("checkbox", name=re.compile(re.escape(layer) + r"$"))
        expect(row).to_have_count(1)
        page.locator("#service").select_option("wms")

        def operation(response, request, field):
            params = {key.upper(): value[0] for key, value in parse_qs(urlsplit(response.url).query).items()}
            return params.get("REQUEST", "").upper() == request and params.get(field) == layer

        with page.expect_response(lambda r: operation(r, "GETMAP", "LAYERS")) as rendered:
            row.check()
        assert rendered.value.body().startswith(b"\x89PNG\r\n\x1a\n"), "Expected a WMS PNG"
        page.get_by_role("button", name="Search objects").click()
        page.locator("#objectType").select_option(layer)
        with page.expect_response(lambda r: operation(r, "GETFEATURE", "TYPENAME")) as found:
            page.get_by_role("button", name="Search", exact=True).click()
        assert found.value.json()["features"], "No ENC geometry in the chart viewport"
        result = page.locator("#results button").first
        result.click()
        expect(result).to_have_attribute("aria-pressed", "true")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Public GeoServer base URL")
    parser.add_argument("--layer", required=True, help="Qualified name of the published ENC feature type")
    parser.add_argument("--chromium", help="Optional path to a Chromium executable")
    args = parser.parse_args()
    check(args.url, args.layer, args.chromium)
