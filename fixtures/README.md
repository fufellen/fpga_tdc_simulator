# Золотые фикстуры из RTL-репозитория

Побайтные копии артефактов симуляции ВЦП из read-only эталона
`C:\workspace\verilog-fpga-tdc\src\TDC\fpga_tdc\`
(репозиторий `verilog`, ветка `fpga_tdc`, коммит `aadf5b89`):

| файл | что это | SHA-256 |
| --- | --- | --- |
| `code_density.dat` | гистограмма плотности кодов, 40000 хитов, кривая линия (ModelSim 10.5b, `tdc_code_density_tb.sv`) | `1E7DBDEE5816D82589D2C28CDE4CB3ACD80A4C9E65CF63F4C0E109C88D62476D` |
| `calibration.hex` | калибровочная LUT, построенная `analyze_inl_dnl.py` из этой гистограммы | `E96576BDC1DB891E035C8CB99753EC126E8FA9AE6192A2C17C7BA11906A4F609` |

Файлы используются как золотые векторы: порт анализа плотности кодов
обязан из `code_density.dat` получать `calibration.hex` побайтно
(тест `tests/test_density.py`). Не редактировать; при обновлении RTL
скопировать новые версии и обновить хэши и коммит.
