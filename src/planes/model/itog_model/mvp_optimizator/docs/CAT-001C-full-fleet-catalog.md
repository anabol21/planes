# CAT-001C — complete selectable fleet catalog

**Baseline:** CAT-001B `c8ce7c834576e4262e26c26b20539141f6d4c7e3`
**Contract:** v0 unchanged
**Physical source of truth:** model `data/data.json`; runtime `fleet_catalog.json` mirrors selection IDs, compatibility, spectra and user-facing provenance.

## Selectable UAV configurations

| UAV | Mass | Payload semantics/value | Airspeed max | Survey | Climb | Descent | Flight time | Battery | Power | Reserve | Max wind | Provenance |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---:|---:|---|
| Geoscan Gemini | 2 kg, aircraft + battery + propellers | 0.5 kg, synthetic additional-payload metadata; not an operational limit and not added to mass | 15 m/s | 12 m/s estimate | 5 m/s | 5 m/s estimate | 40 min | Li-Ion, 21.6 V, 6.7 Ah, 144.7 Wh | rotor cubic coefficients (estimates) | 5% estimate | 10 m/s | Passport aircraft/battery specs; working speed/physics assumptions in marked model fields |
| Geoscan 201 | 8.5 kg MTOW including payload | 1.5 kg passport maximum payload; never added to MTOW | 36.11 m/s calculated from 130 km/h | 25 m/s estimate | 3 m/s estimate | 2 m/s synthetic | 180 min advertised | LiPo 5S, 18.5 V, 40 Ah, 740 Wh calculated | 220 W constant estimate | 5% estimate | 12 m/s | Manufacturer manual plus marked MVP assumptions/calculations |
| Geoscan 801 | 1.5 kg, treated as complete integrated camera configuration | N/A: no additional user payload in the selected fixed integrated-camera entry | 15 m/s | 12 m/s estimate | 4 m/s estimate | 0.5 m/s estimate | 40 min | Li-Po, 15.4 V, 8.2 Ah, 126.28 Wh | rotor cubic coefficients (estimates) | 5% estimate | 10 m/s | Manufacturer manual/specs plus marked MVP assumptions |

The Gemini payload figure is explicitly synthetic metadata: the current product specification does not publish a scalar additional-payload capacity. An older official Geoscan seminar table reports a different historical configuration, so its figures are not silently applied to the current selected configuration. Assumed range is 0.25–2.0 kg; 0.5 kg is a conservative MVP placeholder only and must not be treated as a safe operating limit. It is not consumed by the solver. The 801 N/A value refers only to *additional* payload beyond the fixed integrated camera configuration; the documented 1.5 kg mass is not increased.

Battery model metadata includes typed chemistry, nominal voltage, capacity and energy values alongside the historical text fields. The 201 energy is `40 Ah × 18.5 V = 740 Wh`; Gemini's `21.6 V × 6.7 Ah = 144.72 Wh` is manufacturer-rounded to `144.7 Wh`; 801's `15.4 V × 8.2 Ah = 126.28 Wh` matches its manual.

## Selectable camera configurations

| Camera | Compatible UAV | Spectrum | Sensor | Focal configuration | Image pixels | Bands / range | Provenance | Runnable |
|---|---|---|---|---|---:|---|---|---|
| Geoscan PF1B | Gemini | RGB | 23.5 × 15.6 mm | 20 mm | 6000 × 4000 | N/A (RGB discrete centres) | Existing committed specs; CAT-001A | YES |
| Sony UMC-R10C 16 | Gemini | RGB | 23.2 × 15.4 mm | 16 mm | 5456 × 3632 | Existing marked estimate; CAT-001A | YES |
| Sony UMC-R10C 20 | Gemini | RGB | 23.2 × 15.4 mm | 20 mm | 5456 × 3632 | Existing marked estimate; CAT-001A | YES |
| Geoscan Pollux | Gemini, 201 | RGB, multispectral | 5.04 × 3.78 mm | 8 mm | 1440 × 1080 | Sensor calculated from 6.3 mm diagonal and 4:3 aspect; five retained passport centres | YES |
| Riebo R4 | 201 | RGB | 35.9 × 24 mm | 40 mm | 8204 × 5485 | Existing square-pixel calculation from 45 MP and sensor aspect; not passport pixel dimensions | YES |
| Riebo R6 | 201 | RGB | 35.9 × 24 mm | 40 mm | 9552 × 6386 | Existing square-pixel calculation from 61 MP and sensor aspect; not passport pixel dimensions | YES |
| Sony DSC-RX1RM2 | 201 | RGB | 35.9 × 24 mm | 35 mm | 7952 × 5304 | Sensor passport; lens/pixels retained repository estimates | YES |
| Sony DSC-RX1RM3 | 201 | RGB | 35.7 × 23.8 mm | 35 mm | 9504 × 6336 | Sensor passport; lens/pixels retained repository estimates | YES |
| Sony ZV-E10 + E PZ 16–50 mm OSS | 201 | RGB | 23.5 × 15.6 mm | 16 mm at wide end | 6000 × 4000 | Sensor/resolution Sony passport; installed lens unknown, explicit synthetic mission configuration | YES |
| Geoscan 801 visible 4.35 | 801 | RGB | 6.17 × 4.55 mm | 4.35 mm | 4000 × 3000 | Existing marked optical-format/frame estimates; lens from committed specs | YES |
| Geoscan 801 visible 16 | 801 | RGB | 6.17 × 4.55 mm | 16 mm | 4000 × 3000 | Existing marked optical-format/frame estimates; lens from committed specs | YES |
| Geoscan 801 thermal | 801 | Infrared | 10.88 × 8.704 mm | 9.1 mm | 640 × 512 | Dimensions calculated from repository 17 µm pitch estimate; range 8–14 µm passport | YES |

For every camera except Pollux, `bands: []` means **not applicable**: the runtime field stores discrete multispectral band-centre wavelengths, not ordinary RGB colour channels. The thermal camera's continuous manufacturer range remains separate as `spectral_range_um`.

ZV-E10 is an interchangeable-lens body. [Sony's official ZV-E10 specifications](https://www.sony.com/electronics/support/e-mount-body-zv-e-series/zv-e10/specifications) give the E-mount body, 23.5 × 15.6 mm sensor and 6000 × 4000 maximum still frame; repository sources do not establish the lens mounted on the Geoscan 201. The live catalog therefore selects the explicit 16 mm wide-end mission configuration as `synthetic`; it is configuration metadata, not an intrinsic body focal length. Removing its focal record still produces an explicit geometry error; no generic fallback is restored.

The [Geoscan 801 product specification](https://www.geoscan.ru/ru/products/geoscan801) publishes the thermal camera's 8–14 µm infrared range. The [Geoscan Gemini product page](https://www.geoscan.ru/ru/products/gemini) does not state an additional-payload scalar; the older [Geoscan seminar table](https://www.geoscan.ru/themes/geoscan/assets/seminary/geoscan-weekend-2019/%D0%9A%D0%BB%D0%B5%D1%81%D1%82%D0%BE%D0%B2.%D0%9C%D0%B0%D1%80%D0%BA%D1%88%D0%B5%D0%B9%D0%B4%D0%B5%D1%80%D0%B8%D1%8F.pdf) refers to a different historical configuration and is not silently treated as current passport data.

## Validation and limitations

- All 12 selectable external camera IDs resolve to model camera entries; all 13 declared compatibility edges resolve to complete aircraft physics and camera geometry.
- All selectable runtime UAV/camera `gaps` arrays are empty and contain no unexplained `null` values. Two model-only ambiguous historical aliases (`umc-r10c`, `801-visible`) remain explicitly unsupported and are not selectable IDs.
- No optimizer, geometry formula, routing, terrain, candidate selection, backend, frontend, or public DTO was changed. The existing shared-swath/first-aircraft geometry behavior for heterogeneous missions remains unchanged and outside CAT-001C.
- Marks and source/note details for every existing physical value remain in their respective JSON records; table shorthand does not upgrade repository estimates to passport data.
