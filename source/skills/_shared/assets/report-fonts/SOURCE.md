# Report font source

TrainLab Report Sans Regular is a static derivative of Noto Sans SC under the accompanying SIL Open Font License 1.1. The product includes one font, performs no system font lookup and downloads nothing at runtime.

- Upstream: [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk), Sans2.004, commit `523d033d6cb47f4a80c58a35753646f5c3608a78`.
- [Original font](https://github.com/notofonts/noto-cjk/blob/523d033d6cb47f4a80c58a35753646f5c3608a78/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf).
- [Original license](https://github.com/notofonts/noto-cjk/blob/523d033d6cb47f4a80c58a35753646f5c3608a78/LICENSE), kept unmodified.
- Original font: 17,773,132 bytes; SHA-256 `d68bafcb48a2707749396aa12bbbd833cb70401f3a9a689fd2902c7e0d295964`.
- License SHA-256: `6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2`.
- Upstream bytes verified 2026-09-08, Git blob SHA-1 `5371a543be5fc670c7cdee9760c03554ee3e9b8e`.
- Derived 2026-09-09 with fontTools 4.64.0, fixed `wght=400`, variable axes removed; family, full, unique and PostScript names changed to TrainLab Report Sans. Original copyright and OFL license names remain intact. This derivative does not use the upstream reserved family name.
- `TrainLabReportSans-Regular.ttf`: 10,596,324 bytes; SHA-256 `04120c26e180eba9c6bb137421e68fa157a63aa4315b49de12383ca23dab10a4`.

Reproduction from the verified original in an isolated build directory:

```sh
uv run --no-project --with fonttools==4.64.0 python - <<'PYFONT'
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
font = instantiateVariableFont(TTFont("NotoSansSC-VF.ttf"), {"wght": 400}, inplace=True)
values = {1: "TrainLab Report Sans", 2: "Regular", 3: "TrainLab Report Sans Regular 2.004", 4: "TrainLab Report Sans Regular", 6: "TrainLabReportSans-Regular", 16: "TrainLab Report Sans", 17: "Regular", 25: "TrainLabReportSans"}
for record in font["name"].names:
    if record.nameID in values:
        record.string = values[record.nameID].encode(record.getEncoding())
font["OS/2"].usWeightClass = 400
font["OS/2"].fsSelection = (font["OS/2"].fsSelection & ~0x21) | 0x40
font["head"].macStyle &= ~3
font.recalcTimestamp = False
font.save("TrainLabReportSans-Regular.ttf")
PYFONT
```

fontTools is a one-time build tool, not a product or CI dependency. ReportLab embeds the required glyph subset in each PDF. Font choice is an implementation dependency, not a coaching or page-count requirement.
