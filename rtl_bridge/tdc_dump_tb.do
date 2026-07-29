# Per-vector dump of the reference sweep, run against the read-only RTL.
#
# The RTL directory comes from the TDC_RTL_DIR environment variable so no
# machine-specific path is committed; the config (A/B/C) from TDC_CFG.
#
#   $env:TDC_RTL_DIR = "C:/workspace/verilog-fpga-tdc/src/TDC/fpga_tdc"
#   $env:TDC_CFG     = "B"
#   vsim -batch -do "do rtl_bridge/tdc_dump_tb.do; quit -f"
#
# Nothing is written into the RTL checkout: sources are pulled in with
# +incdir and all simulation files stay under rtl_bridge/_sim.

catch {quit -sim}
transcript off

onerror     {quit -code 1}
onElabError {quit -code 12}
onbreak     {resume}

if {![info exists ::env(TDC_RTL_DIR)]} {
    error "Set TDC_RTL_DIR to the reference fpga_tdc directory"
}
set rtl_dir [file normalize $::env(TDC_RTL_DIR)]
if {![file exists [file join $rtl_dir tdc_top.sv]]} {
    error "tdc_top.sv not found in $rtl_dir"
}

# `info script` is unreliable inside a ModelSim `do`, so the runner
# passes this directory explicitly.
if {![info exists ::env(TDC_BRIDGE_DIR)]} {
    error "Set TDC_BRIDGE_DIR to the rtl_bridge directory"
}
set script_dir [file normalize $::env(TDC_BRIDGE_DIR)]
set sim_dir    [file join $script_dir _sim]
set out_dir    [file join $script_dir dumps]
file mkdir $sim_dir
file mkdir $out_dir

# fresh work library inside _sim so repeated runs cannot pick up stale units
foreach pattern {work modelsim.ini vsim.wlf *.wlf} {
    foreach path [glob -nocomplain -directory $sim_dir $pattern] {
        file delete -force $path
    }
}
cd $sim_dir
catch {unset ::env(MODELSIM)}
vmap -c
set ::env(MODELSIM) [file join $sim_dir modelsim.ini]
vlib work
vmap work [file join $sim_dir work]

set cfg "A"
if {[info exists ::env(TDC_CFG)]} { set cfg $::env(TDC_CFG) }

vlog -sv +incdir+$rtl_dir +incdir+$script_dir \
    [file join $script_dir tdc_dump_tb.sv]

set dump [file join $out_dir "modelsim_sweep_$cfg.csv"]
set args [list -t 1ps -voptargs="+acc" work.tdc_dump_tb "+DUMP=$dump"]
switch -exact -- $cfg {
    A { }
    B { lappend args "+NONUNIF" }
    C { lappend args "+NONUNIF" "+CALIB=[file join $rtl_dir calibration.hex]" }
    default { error "Unknown TDC_CFG '$cfg' (expected A, B or C)" }
}
eval vsim $args

run -all
quit -code 0
