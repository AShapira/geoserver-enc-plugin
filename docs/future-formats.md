# S-62, S-63 and S-101 extension options

## S-62 producer metadata

[IHO S-62](https://registry.iho.int/producercode/list2.do) registers producer identifiers. It does not define an ENC file encoding. This plugin already preserves S-57 `AGEN`, `LNAM`, `LNAM_REFS`, and `FFPT_RIND`; the cache's `DSID` table retains `DSID_AGEN`. The NOAA samples identify producer 550.

Suggested addition: import a versioned CSV export of the IHO producer register, retaining its download date and checksum. Resolve `AGEN` to producer name/country for GetFeatureInfo and layer metadata. Keep numeric source identifiers unchanged, retain unknown codes, and avoid making live register availability a prerequisite for map rendering. Add tests for unknown, retired, and changed producer codes. No additional chart reader is required.

## If S-63 encrypted ENC was intended

S-63 is the [IHO data-protection scheme](https://iho.int/s-63-faq). The current plugin does not decrypt S-63 cells or accept permit files. Do not point `ogr2ogr` at an encrypted exchange set and assume S57 support includes decryption.

Proposed architecture:

1. A separate authorized import service validates the exchange set, signatures/certificate chain, applicable cell permits and permit validity using an appropriate S-63 implementation. Select an implementation whose licensing and IHO participation requirements fit the deployment.
2. The service produces a verified, plaintext S-57 base/update set in restricted storage. Pass that set through this plugin's existing GDAL import and update validation. Keep permit secrets and device identity outside GeoServer datastore parameters and logs.
3. Record input hashes, permitted edition/update, verification result and effective authorization period. Coordinate permit expiry/revocation with WMS access and every derivative tile/cache location.
4. Confirm the chart supplier permits the intended server publication and tile redistribution before enabling that publication. Test with IHO's S-63 test datasets and legitimate permits; no cryptographic bypass is proposed.

The GeoServer reader, portrayal compiler and WMS/WMTS stack can be reused after authorized decryption. The entitlement boundary, storage policy and cache lifecycle need new implementation and integration tests. No S-63 runtime claim is made.

## S-101 / S-100

S-101 is a different ENC product model with separately versioned feature and portrayal catalogues. The [IHO product resource page](https://iho-ohi.github.io/S100Resources/) publishes these resources; [IHO's product-specification overview](https://iho.int/en/s-100-based-product-specifications) explains their relationship.

Keep a decoder boundary separate from portrayal: a future `S101Importer` should preserve S-100 feature associations, complex attributes, catalogue version, vertical reference and coverage metadata in a suitable indexed model. Add an S-100 portrayal engine for its catalogue and conditional rules. The existing Java DataStore serving pattern and GeoServer protocols are reusable, but the S57 GDAL driver and this S-52 lookup compiler are not a complete S-101 implementation. A controlled S-101-to-S-57 conversion could be a limited migration route, only with an explicit loss report and validation. Reader availability and catalogue compatibility must be verified against the chosen future library/version.
