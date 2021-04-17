###############################################################################
###############################################################################
from pybfms.bfm_mgr import BfmMgr
from pybfms import BfmType

"""Generates the HDL BFM shell based on loaded Python BFM classes"""

import os
import argparse
import importlib
from string import Template

def bfm_load_modules(module_l):
    for m in module_l:
        importlib.import_module(m)

def process_template_vl(template, info):
    """Process a single BFM-HDL template file string (template),
    substituting generated interface tasks and task-call demux
    based on BFM task declarations (info). Returns complete
    BFM Verilog module as a string"""

    t = Template(template)

    bfm_import_calls = ""
    
    if info.has_init:
        bfm_import_calls += "              'h8000: begin\n"
        bfm_import_calls += "                  init();\n"
        bfm_import_calls += "              end\n"
        
    for i,imp in enumerate(info.import_info):
        bfm_import_calls += "              " + str(i) + ": begin\n"
        bfm_import_calls += "                  " + imp.T.__name__  + "(\n"
        for pi,p in enumerate(imp.signature):
            if p.ptype.s:
                bfm_import_calls += "                      $pybfms_get_param_i32(bfm_id)"
            else:
                bfm_import_calls += "                      $pybfms_get_param_ui32(bfm_id)"

            if pi+1 < len(imp.signature):
                bfm_import_calls += ","
            bfm_import_calls += "\n"
        bfm_import_calls += "                      );\n"
        bfm_import_calls += "              end\n"

    bfm_export_tasks = ""
    for i,exp in enumerate(info.export_info):
        bfm_export_tasks += "    task " + exp.T.__name__

        if len(exp.signature) > 0:
            bfm_export_tasks += "("
            for j,p in enumerate(exp.signature):
                bfm_export_tasks += "input " + p.ptype.vl_type() + " " + p.pname
                if j+1 < len(exp.signature):
                    bfm_export_tasks += ", "
            bfm_export_tasks += ");\n"
        else:
            bfm_export_tasks += ";\n"
        bfm_export_tasks += "    begin\n"
        bfm_export_tasks += "        $pybfms_begin_msg(bfm_id, " + str(i) + ");\n"
        for p in exp.signature:
            if p.ptype.s:
                bfm_export_tasks += "        $pybfms_add_param_si(bfm_id, " + p.pname + ");\n"
            else:
                bfm_export_tasks += "        $pybfms_add_param_ui(bfm_id, " + p.pname + ");\n"

        bfm_export_tasks += "        $pybfms_end_msg(bfm_id);\n"
        bfm_export_tasks += "        // Check to see if a message came in response\n"
        bfm_export_tasks += "        bfm_msg_id = $pybfms_claim_msg(bfm_id);\n"
        bfm_export_tasks += "        if (bfm_msg_id != -1) begin\n"
        bfm_export_tasks += "            __dispatch_bfm_msg(bfm_msg_id);\n"
        bfm_export_tasks += "        end\n"
        bfm_export_tasks += "\n"
        
        bfm_export_tasks += "    end\n"
        bfm_export_tasks += "    endtask\n"

    impl_param_m = dict(
        bfm_classname=info.T.__module__+"."+info.T.__qualname__,
        bfm_import_calls=bfm_import_calls,
        bfm_export_tasks=bfm_export_tasks
        )

    pybfms_api_impl = """
    reg signed[31:0]      bfm_id = -1;
`ifdef IVERILOG
    event                 bfm_ev;
`else
    reg                 bfm_ev = 0;
`endif
    reg signed[31:0]      bfm_msg_id;

${bfm_export_tasks}

    task __dispatch_bfm_msg(input reg signed[31:0] bfm_msg_id);
    begin
          case (bfm_msg_id)
${bfm_import_calls}
              -1: begin
              $finish;
              end
          endcase
    end
    endtask

    initial begin
      bfm_id = $pybfms_register("${bfm_classname}", bfm_ev);
      
      while (1) begin
          bfm_msg_id = $pybfms_claim_msg(bfm_id);

            if (bfm_msg_id != -1) begin
                __dispatch_bfm_msg(bfm_msg_id);
            end else begin
                @(bfm_ev);
            end
      end
    end
    """

    param_m = {
        "pybfms_api_impl" : Template(pybfms_api_impl).safe_substitute(impl_param_m)
        }


    return t.safe_substitute(param_m)

def bfm_generate_vl(args):
    inst = BfmMgr.inst()

    with open(args.o, "w") as out:
        out.write("//***************************************************************************\n")
        out.write("//* BFMs file for pybfms. \n")
        out.write("//* Note: This file is generated by pybfms.bfmgen. Do Not Edit\n")
        out.write("//***************************************************************************\n")
        out.write("\n")
        out.write("`define PYBFMS_GEN\n")

        for t,info in inst.bfm_type_info_m.items():

            if BfmType.Verilog not in info.hdl.keys():
                raise Exception("BFM {!r} does not support Verilog".format(t.__name__))

            with open(info.hdl[BfmType.Verilog], "r") as template_f:
                template = template_f.read()

            out.write(process_template_vl(template, info))
            
        out.write("`undef PYBFMS_GEN\n")

def process_template_sv(template, bfm_name, info):
    """Process a single BFM-HDL template file string (template),
    substituting generated interface tasks and task-call demux
    based on BFM task declarations (info). Returns complete
    BFM SystemVerilog module as a string"""

    t = Template(template)

    bfm_import_calls = ""
    if info.has_init:
        bfm_import_calls += "              'h8000: begin\n"
        bfm_import_calls += "                  init();\n"
        bfm_import_calls += "              end\n"
        
    for i,imp in enumerate(info.import_info):
        bfm_import_calls += "              " + str(i) + ": begin\n"
        # Verilator doesn't evaluate expressions in the order that
        # they appear in the argument list. Consequently, we need
        # to create temporary variables to ensure the order is correct.
        for pi,p in enumerate(imp.signature):
            if p.ptype.s:
                bfm_import_calls += "                  longint p" + str(pi) + " = pybfms_get_si_param(bfm_id);\n"
            else:
                bfm_import_calls += "                  longint unsigned p" + str(pi) + " = pybfms_get_ui_param(bfm_id);\n"

        bfm_import_calls += "                  " + imp.T.__name__  + "(\n"
        for pi in range(len(imp.signature)):
            bfm_import_calls += "                      p" + str(pi)

            if pi+1 < len(imp.signature):
                bfm_import_calls += ","
            bfm_import_calls += "\n"
        bfm_import_calls += "                      );\n"
        bfm_import_calls += "              end\n"

    bfm_export_tasks = ""
    for i,exp in enumerate(info.export_info):
        bfm_export_tasks += "    task " + exp.T.__name__ + "("
        for j,p in enumerate(exp.signature):
            bfm_export_tasks += "input " + p.ptype.vl_type() + " " + p.pname
            if j+1 < len(exp.signature):
                bfm_export_tasks += ", "
        bfm_export_tasks += ");\n"
        bfm_export_tasks += "    begin\n"
        bfm_export_tasks += "        if (bfm_id < 0) begin\n"
        bfm_export_tasks += "            $display(\"Error: %m not registered\");\n"
        bfm_export_tasks += "            $finish();\n"
        bfm_export_tasks += "        end\n";
        bfm_export_tasks += "        pybfms_begin_msg(bfm_id, " + str(i) + ");\n"
        for p in exp.signature:
            if p.ptype.s:
                bfm_export_tasks += "        pybfms_add_si_param(bfm_id, " + p.pname + ");\n"
            else:
                bfm_export_tasks += "        pybfms_add_ui_param(bfm_id, {});\n".format(p.pname)

        bfm_export_tasks += "        pybfms_end_msg(bfm_id);\n"
        bfm_export_tasks += "    end\n"
        bfm_export_tasks += "    endtask\n"


    impl_param_m = {
        "bfm_name" : bfm_name,
        "bfm_classname" : info.T.__module__ + "." + info.T.__qualname__,
        "bfm_import_calls" : bfm_import_calls,
        "bfm_export_tasks" : bfm_export_tasks
        }

    pybfms_api_impl = """
    int          bfm_id;

    import "DPI-C" context function int pybfms_register(
        string     iname,
        string     clsname,
        chandle    notify_cb,
        chandle    notify_ud);
    import "DPI-C" context function int pybfms_claim_msg(int bfm_id);
    import "DPI-C" context function longint pybfms_get_si_param(int bfm_id);
    import "DPI-C" context function longint unsigned pybfms_get_ui_param(int bfm_id);
    import "DPI-C" context function void pybfms_begin_msg(int bfm_id, int msg_id);
    import "DPI-C" context function void pybfms_add_si_param(int bfm_id, longint v);
    import "DPI-C" context function void pybfms_add_ui_param(int bfm_id, longint unsigned v);
    import "DPI-C" context task pybfms_end_msg(int bfm_id);

    task automatic ${bfm_name}_process_msg();
        int msg_id;
        msg_id = pybfms_claim_msg(bfm_id);
        case (msg_id)
${bfm_import_calls}
        default: begin
            $display("Error: BFM %m received unsupported message with id %0d", msg_id);
            $finish();
        end
        endcase
    endtask
    export "DPI-C" task ${bfm_name}_process_msg;
    import "DPI-C" context function int ${bfm_name}_register(string inst_name);
   
    /*
    function automatic int ${bfm_name}_register_w(
        string         iname,
        string         clsname,
        chandle        notify_cb,
        chandle        notify_ud);
        return pybfms_register(iname, clsname, notify_cb, notify_ud);
    endfunction
    export "DPI-C" function ${bfm_name}_register_w;
     */
        

${bfm_export_tasks}

    initial begin
      bfm_id = ${bfm_name}_register($sformatf("%m"));
      $display("PyBfms: register ${bfm_name} %m (bfm_id=%0d)", bfm_id);
    end
    """

    param_m = {
        "pybfms_api_impl" : Template(pybfms_api_impl).safe_substitute(impl_param_m)
        }


    return t.safe_substitute(param_m)

def generate_dpi_c(bfm_name, info):
    template_p = {
        "bfm_name" : bfm_name,
        "bfm_classname" : info.T.__module__ + "." + info.T.__qualname__,
        }

    template = """
    extern "C" int ${bfm_name}_process_msg() __attribute__((weak));

// Stub definition to handle the case where a referenced
// BFM type isn't instanced
/*
int ${bfm_name}_process_msg() { 
    fprintf(stdout, "${bfm_name}_process_msg(weak)\\n");
    return -1; }
 */

static void ${bfm_name}_notify_cb(void *user_data) {
    svSetScope(user_data);
    if (${bfm_name}_process_msg) {
        ${bfm_name}_process_msg();
    } else {
       fprintf(stdout, "No process_msg\\n");
    }
}


int ${bfm_name}_register_w(const char *, const char *, pybfms_notify_f, void *) __attribute__((weak));
// Stub definition
int ${bfm_name}_register_w(const char *iname, const char *cname, pybfms_notify_f f, void *ud) { return -1; }

int ${bfm_name}_register(const char *inst_name) {
    void *ctxt = svGetScope();
    int id;
    
    id = pybfms_register(
        inst_name,
        \"${bfm_classname}\",
        &${bfm_name}_notify_cb,
        ctxt);
        
    return id;
}
"""

    return Template(template).safe_substitute(template_p)

def bfm_generate_sv(args):
    inst = BfmMgr.inst()

    filename_c = args.o
    if filename_c.find('.') != -1:
        filename_c = os.path.splitext(filename_c)[0]
    filename_c += ".c"

    with open(args.o, "w") as out_sv:
        with open(filename_c, "w") as out_c:
            out_sv.write("//***************************************************************************\n")
            out_sv.write("//* BFMs file for pybfms. \n")
            out_sv.write("//* Note: This file is generated. Do Not Edit\n")
            out_sv.write("//***************************************************************************\n")
            out_sv.write("`define PYBFMS_GEN\n")

            out_c.write("//***************************************************************************\n")
            out_c.write("//* BFMs DPI interface file for pybfms. \n")
            out_c.write("//* Note: This file is generated. Do Not Edit\n")
            out_c.write("//***************************************************************************\n")
            out_c.write("#include <stdio.h>\n")
            out_c.write("#ifdef __cplusplus\n")
            out_c.write("extern \"C\" {\n")
            out_c.write("#endif\n")
            out_c.write("\n")
            out_c.write("#include \"svdpi.h\"\n")
            out_c.write("#define _GNU_SOURCE\n")
            out_c.write("#define __USE_GNU\n")
            out_c.write("#include <dlfcn.h>\n")
            out_c.write("typedef void (*pybfms_notify_f)(void *);\n")
            out_c.write("int pybfms_register(const char *, const char *,pybfms_notify_f, void *);\n")
            out_c.write("\n");

            for t,info in inst.bfm_type_info_m.items():
                if BfmType.Verilog not in info.hdl.keys():
                    raise Exception("BFM \"" + t.__name__ + "\" does not support Verilog")

                with open(info.hdl[BfmType.SystemVerilog], "r") as template_f:
                    template = template_f.read()

                bfm_name = os.path.basename(info.hdl[BfmType.SystemVerilog])

                if bfm_name.find('.') != -1:
                    bfm_name = os.path.splitext(bfm_name)[0]

                out_sv.write(process_template_sv(template, bfm_name, info))
                out_c.write(generate_dpi_c(bfm_name, info))

            out_c.write("#ifdef __cplusplus\n")
            out_c.write("}\n")
            out_c.write("#endif\n")
            out_sv.write("`undef PYBFMS_GEN\n")

def bfm_generate(args):
    """Generate BFM files required for simulation"""
    
    if hasattr(args, 'm') and args.m is not None:
        bfm_load_modules(args.m)

    if args.o is None:
        if args.language == "vlog":
            args.o = "pybfms.v"
        elif args.language == "sv":
            args.o = "pybfms.sv"
        elif args.language == "vhdl":
            args.o = "pybfms.vhd"

    if args.language == "vlog":
        bfm_generate_vl(args)
    elif args.language == "sv":
        bfm_generate_sv(args)
    elif args.language == "vhdl":
        raise Exception("VHDL currently unsupported")
    else:
        raise Exception("unsupported language \"" + args.language + "\"")

def get_parser():
    parser = argparse.ArgumentParser(prog="pybfms.bfmgen")

    subparser = parser.add_subparsers()
    subparser.required = True
    subparser.dest = 'command'
    generate_cmd = subparser.add_parser("generate")
    generate_cmd.set_defaults(func=bfm_generate)
    generate_cmd.add_argument("-m", action='append')
    generate_cmd.add_argument("-l", "--language", default="vlog",
        choices=["vlog", "sv", "vhdl"])
    generate_cmd.add_argument("-o", default=None)

    return parser

def main():
    parser = get_parser()

    args = parser.parse_args()

    # Ensure the BfmMgr is created
    BfmMgr.inst()

    if hasattr(args, 'm') and args.m is not None:
        bfm_load_modules(args.m)

    args.func(args)


if __name__ == "__main__":
    main()
