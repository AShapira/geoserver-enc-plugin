# Licensing and provenance

Project source is GPL-2.0-or-later. See `LICENSE`. The distributed plugin links to GeoTools and is designed for GeoServer; their own licenses continue to apply.

`portrayal/upstream/chartsymbols.xml` and the three `rastersymbols-*.png` files are unmodified copies from **OpenCPN/OpenCPN**, commit `8c8d64570a80e0791e3b7c0a1a88f9315eea09e7`. OpenCPN and its contributors retain their copyrights. The original GPL v2 license text is preserved in `portrayal/upstream/COPYING`; exact source URLs and SHA-256 hashes are in `portrayal/upstream/manifest.json`. Generated SLDs, cropped symbols and HPGL renderings derive from these resources and are distributed under GPL-2.0-or-later with this source. No official IHO conformance or endorsement is implied.

Source: https://github.com/OpenCPN/OpenCPN/tree/8c8d64570a80e0791e3b7c0a1a88f9315eea09e7/data/s57data

The sounding, restriction and topmark procedures in `S52GraphicFactory.java`, and light/text adaptations in it and `EncFunctionFactory.java`, derive from OpenCPN `Release_5.12.4`, commit `37fd0cddb7334fe489e9f18aa163977a9c5c84f7`, especially `libs/s52plib/src/s52cnsy.cpp` and `s52plib.cpp`. Copyright remains with the OpenCPN authors and contributors; these adaptations are GPL-2.0-or-later. The reference viewer is the unmodified Ubuntu OpenCPN 5.12.4 package. Original attribution and the GPL license remain available in that source distribution: https://github.com/OpenCPN/OpenCPN/tree/Release_5.12.4/libs/s52plib .

NOAA ENC data is fetched separately from https://charts.noaa.gov/ENCs/ENCsIndvDole.shtml. Each download includes a provenance manifest and retains NOAA's exchange-set files and notices. Raw ENC downloads, local tools and GeoServer binaries are not included in the plugin archive. Rendered evidence derives from NOAA ENC data and the above portrayal resources. Charts are current only to the downloaded exchange set; nothing in the plugin refreshes them automatically.

The bootstrap downloads third-party binaries using pinned versions/checksums. Each component retains its upstream license; the local environment and GeoServer distributions include their notices. No native GDAL/JDK/Maven binaries are bundled in the plugin JAR.
