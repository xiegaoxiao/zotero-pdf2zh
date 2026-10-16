# Sparse MacRoman test fixture

`sparse-macroman-ticks.pdf` is a synthetic one-page PDF containing the text `20`, `30`, and `40`. Its TrueType font uses simple geometric shapes generated for this regression test, not glyphs copied from a third-party font or a paper.

The fixture exercises sparse MacRoman character maps that older MuPDF native font subsetting can remap incorrectly. Tests compare rendered pixels and extracted text separately.

To regenerate it, install the optional developer dependencies `fonttools` and `PyMuPDF`, then run from `server`:

```sh
python tests/fixtures/generate_sparse_macroman.py
```

The generator reports whether the installed MuPDF version reproduces the native visual corruption. Newer versions may already have fixed it. Generation timestamps can make the binary checksum differ across runs.
