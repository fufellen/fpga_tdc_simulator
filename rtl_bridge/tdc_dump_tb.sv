`timescale 1ps/1ps
`define TDC_SIM
`define TDC_LOAD_CALIB
`include "tdc_top.sv"
// Per-vector dump of the reference interval sweep.
//
// Same stimulus as tdc_top_tb.sv in the read-only RTL checkout, but it
// writes every point to CSV instead of printing aggregates only. The
// CSV becomes the golden fixture the Python port is compared against
// vector by vector (the reference bench prints only max/RMS/fails).
//
// The RTL itself is NOT modified: tdc_top.sv is pulled in through
// +incdir pointing at the reference directory.
//
// Plusargs: +NONUNIF (crooked line on both channels),
//           +CALIB=<hex> (calibration LUT),
//           +DUMP=<csv>  (output file, default tdc_sweep_dump.csv).
// Requires vsim -t 1ps.
module tdc_dump_tb;
    localparam int NTAP  = 100;
    localparam int TCLK  = 5000;   // пс -> 200 МГц
    localparam int LSB   = 50;     // пс
    localparam int PULSE = 7000;   // высокий уровень hit [пс]

    logic clk = 1'b0;
    always #(TCLK/2) clk = ~clk;

    logic rst = 1'b1;
    logic start_hit = 1'b0, stop_hit = 1'b0;

    logic signed [31:0] interval_ps;
    logic               interval_valid;
    logic [15:0] scoarse, pcoarse; logic [6:0] sfine, pfine; logic svld, pvld;

    tdc_top #(.NTAP(NTAP), .FW(7), .CW(16), .TW(20), .DTW(32),
              .TCLK_PS(TCLK), .LSB_PS(LSB)) o_tdc (
        .clk(clk), .rst(rst), .start_hit(start_hit), .stop_hit(stop_hit),
        .interval_ps(interval_ps), .interval_valid(interval_valid),
        .dbg_start_coarse(scoarse), .dbg_start_fine(sfine), .dbg_start_valid(svld),
        .dbg_stop_coarse(pcoarse),  .dbg_stop_fine(pfine),  .dbg_stop_valid(pvld));

    int dt, meas, n, j, guard, fd;
    int m_scoarse, m_sfine, m_pcoarse, m_pfine, m_guard;
    string dumpfile;

    // identical to run_one() of the reference bench, plus latching the
    // debug outputs at the moment the interval becomes valid
    task run_one(input int dt_ps);
        begin
            start_hit = 1'b0; stop_hit = 1'b0;
            @(posedge clk); #1234;                 // СТАРТ в середину периода
            start_hit = 1'b1;
            fork
                begin #(PULSE) start_hit = 1'b0; end
                begin #(dt_ps) stop_hit = 1'b1; #(PULSE) stop_hit = 1'b0; end
            join
            guard = 0;
            while (!interval_valid && guard < 200) begin @(posedge clk); guard++; end
            meas      = interval_ps;
            m_scoarse = scoarse; m_sfine = sfine;
            m_pcoarse = pcoarse; m_pfine = pfine;
            m_guard   = guard;
            #(20000);                              // дать линиям стечь
        end
    endtask

    initial begin
        if (!$value$plusargs("DUMP=%s", dumpfile))
            dumpfile = "tdc_sweep_dump.csv";

        repeat (5) @(posedge clk); rst = 1'b0; repeat (3) @(posedge clk);

        if ($test$plusargs("NONUNIF")) begin
            for (j = 0; j < NTAP; j++) begin
                o_tdc.o_start.o_line.tapdly_ps[j] = 40 + (20*j)/(NTAP-1);
                o_tdc.o_stop .o_line.tapdly_ps[j] = 40 + (20*j)/(NTAP-1);
            end
            o_tdc.o_start.o_line.tapdly_ps[25] = 110; o_tdc.o_stop.o_line.tapdly_ps[25] = 110;
            o_tdc.o_start.o_line.tapdly_ps[50] = 110; o_tdc.o_stop.o_line.tapdly_ps[50] = 110;
            $display("[cfg] non-uniform delay line loaded on both channels");
        end
        if ($test$plusargs("CALIB")) $display("[cfg] calibration LUT loaded");

        run_one(4000);   // прогрев, не считаем (как в эталонном tb)

        fd = $fopen(dumpfile, "w");
        $fwrite(fd, "# dt_ps,meas_ps,start_coarse,start_fine,stop_coarse,stop_fine,guard\n");
        n = 0;
        for (dt = 800; dt <= 53000; dt += 173) begin
            run_one(dt);
            $fwrite(fd, "%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",
                    dt, meas, m_scoarse, m_sfine, m_pcoarse, m_pfine, m_guard);
            n++;
        end
        $fclose(fd);
        $display("dump done: %0d points -> %s", n, dumpfile);
        $finish;
    end
endmodule
