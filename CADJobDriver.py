import sys
import os
import argparse
import subprocess
import random
import string
import shutil
import logging
import datetime
import inspect
import cad_library

print_cmds = True


def get_function_name():
    function_name = inspect.currentframe().f_back
    return function_name


class CADJobDriver():

    def __init__(self, assembler, mesher, analyzer, mode, run_postprocessing=True):

        self.logger = None
        self.get_logger()

        if assembler is None:
            assembler = 'CREO'
            self.logger.warning('No assembler specified.')

        if mesher is None:
            mesher = 'NONE'
            self.logger.warning('No mesher specified.')

        if analyzer is None:
            analyzer = 'NONE'
            self.logger.warning('No analyzer specified.')

        if mode is None:
            mode = 'STATIC'
            self.logger.warning('No mode specified.')

        self.logger.info('Assembler: {}'.format(assembler))
        self.logger.info('Mesher: {}'.format(mesher))
        self.logger.info('Analyzer: {}'.format(analyzer))
        self.logger.info('Mode: {}'.format(mode))

        self.assembler = assembler
        self.mesher = mesher
        self.analyzer = analyzer
        self.mode = mode

        self.run_pp = run_postprocessing

        self.run_job()

    def run_job(self):

        # Run assembler
        if self.assembler == 'CREO':
            self.logger.info("Calling CREO...")

            result = 42

            try:
                result = self.run_creo_assembler()
                self.logger.info("CADCreoCreateAssembly Result: {}".format(result))
            except Exception:
                self.logger.error("CADCreoCreateAssembly Exception. See {}".format("log/cad-assembler.log"))
                cad_library.exitwitherror(
                    'CADJobDriver.py: The CreateAssembly threw an Exception. See {}'.format(
                        "log/cad-assembler.log"), -1)

            if result != 0:
                cad_library.exitwitherror(
                    'CADJobDriver.py: The CreateAssembly program returned with error: ' + str(result), -1)

        elif self.assembler == 'ASSEMBLY_EXISTS':
            self.logger.info('CadAssembly has already exists.')

        else:
            cad_library.exitwitherror('CADJobDriver.py: Only CREO assembler is supported.', -1)

        # Run mesher
        if self.mesher == 'ABAQUS' or self.mesher == 'ABAQUSMDLCHECK':
            if self.analyzer == 'NONE':
                self.run_abaqus_model_based(True, self.mesher == 'ABAQUSMDLCHECK')
            elif self.analyzer == 'ABAQUSMODEL':
                self.run_abaqus_model_based(False, False, self.mode)
            else:
                cad_library.exitwitherror('Abaqus mesher only supports Abaqus Model-Based.',-1)
        elif self.mesher == 'PATRAN':
            if self.analyzer == 'PATRAN_NASTRAN':
                self.logger.info("Calling Patran/Nastran")
                self.run_patran_nastran()
            else:
                cad_library.exitwitherror('CADJobDriver.py: mesher=PATRAN requires analyzer=PATRAN_NASTRAN', -1)
        elif self.mesher == 'CREO':
            # Skipping, CREO has already been invoked
            pass
        elif self.mesher == 'NONE':
            # Not meshing, skip analysis
            self.copy_failed_and_exit(0)
        else:
            cad_library.exitwitherror('CADJobDriver.py: Mesher ' + self.mesher + ' is not supported.', -1)

        # Run analyzer
        if self.analyzer == 'ABAQUSMODEL':
            pass
            if self.mesher == 'ABAQUS' or self.mesher == 'ABAQUSMDLCHECK':
                # Skip this, it has already been executed in teh previous section
                pass
            else:
                self.run_abaqus_model_based(False, False, self.mode)
        elif self.analyzer == 'ABAQUSDECK':
            self.run_abaqus_deck_based()
        elif self.analyzer == 'NASTRAN':
            self.run_nastran()
        elif self.analyzer == 'CALCULIX':
            self.run_calculix()

        self.copy_failed_and_exit(0)

    def get_logger(self):

        datetime_now = datetime.datetime.now()

        # create logger with 'spam_application'
        self.logger = logging.getLogger('CADJobDriver')

        self.logger.info("======================================================")
        self.logger.info("    New CADJobDriver Instance: {}".format(datetime_now))
        self.logger.info("======================================================")

    def run_creo_assembler(self):

        isis_ext = os.environ.get('PROE_ISIS_EXTENSIONS')
        if isis_ext is None:
            cad_library.exitwitherror(
                'PROE_ISIS_EXTENSIONS env. variable is not set. Do you have the META toolchain installed properly?', -1)

        create_asm = os.path.join(isis_ext, 'bin', 'CADCreoParametricCreateAssembly.exe')
        if not os.path.isfile(create_asm):
            cad_library.exitwitherror(
                'Cannot find CADCreoParametricCreateAssembly.exe. Do you have the META toolchain installed properly?', -1)

        #logdir = os.path.join(workdir,'log')

        result = os.system('\"' + create_asm + '" -i CADAssembly.xml')

        return result

    def call_subprocess(self, cmd, failonexit = True):
        global print_cmds
        if print_cmds == True:
            print cmd

        result = 0

        try:
            result = subprocess.call(cmd)
        except Exception as e:
            cad_library.exitwitherror('Failed to execute: ' + cmd + ' Error is: ' + e.message, -1)

        if result != 0 and failonexit:
            cad_library.exitwitherror('The command {} exited with value: {}'.format(cmd, result), -1)

        return result

    def copy_failed_and_exit(self, code):
        for (root, dirs, files) in os.walk(os.getcwd(), topdown=False):
            for file in files:
                print os.path.join(root, file)
                if cmp(file, '_FAILED.txt')==0:
                    copy_command = 'copy {} {}'.format(os.path.join(root, file), os.getcwd())
                    os.system('copy ' + os.path.join(root, file) + ' ' + os.getcwd())

        exit(code)

    def run_abaqus_model_based(self, meshonly, modelcheck, mode=None):
        feascript = cad_library.META_PATH + 'bin\\CAD\\Abaqus\\AbaqusMain.py'
        if meshonly:
            if modelcheck:
                param = '-b'
            else:
                param= '-o'
        else:
            if mode == 'STATIC':
                param = '-s'
            elif mode == 'MODAL':
                param = '-m'
            elif mode == 'DYNIMPL':
                param = '-i'
            elif mode == 'DYNEXPL':
                param = '-e'

        self.call_subprocess('c:\\SIMULIA\\Abaqus\\Commands\\abaqus.bat cae noGUI="' + feascript + '" -- ' + param)

    def run_abaqus_deck_based(self):
        id = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        os.chdir(os.getcwd() + '\\Analysis\\Abaqus')
        self.call_subprocess('c:\\SIMULIA\\Abaqus\\Commands\\abaqus.bat fromnastran job=' + id + ' input=..\Nastran_mod.nas')
        self.call_subprocess('c:\\SIMULIA\\Abaqus\\Commands\\abaqus.bat analysis interactive job=' + id)
        self.call_subprocess('c:\\SIMULIA\\Abaqus\\Commands\\abaqus.bat odbreport job=' + id + ' results')
        self.call_subprocess('c:\\SIMULIA\\Abaqus\\Commands\\abaqus.bat cae noGUI="' + cad_library.META_PATH + '\\bin\\CAD\\ABQ_CompletePostProcess.py\" -- -o ' + id + '.odb -p ..\\AnalysisMetaData.xml -m ..\\..\\RequestedMetrics.xml -j ..\\..\\testbench_manifest.json')

    def run_patran_nastran(self):

        meta_bin_cad = os.path.join(cad_library.META_PATH, 'bin', 'CAD')
        meta_src_cad_python = os.path.join(cad_library.META_PATH, 'src', 'CADAssembler', 'Python')
        cpif_name = 'CreatePatranInputFile.py'

        cpif_path = os.path.join(meta_bin_cad, cpif_name)

        # TODO remove this block before deployment
        # ===========================================================
        if not os.path.isfile(cpif_path):
            git_file_path = os.path.join(cad_library.META_PATH, cpif_name)

            try:
                self.logger.info("Looking at {} for {}.".format(git_file_path, cpif_name))
                shutil.copy2(git_file_path, cpif_path)
            except Exception:
                self.logger.error("{} does not exist.".format(cpif_path))
                cad_library.exitwitherror(-33)
        # ===========================================================

        result_dir = os.path.abspath(os.getcwd())
        patran_nastran_dir = os.path.join(result_dir, 'Analysis', 'Patran_Nastran')

        if not os.path.exists(patran_nastran_dir):
            os.makedirs(patran_nastran_dir)

        self.logger.info("Moving to {}.".format(patran_nastran_dir))
        os.chdir(patran_nastran_dir)

        try:
            self.logger.info("Creating Patran Model Input File...")

            from CreatePatranInputFile import PatranPCL
            ppcl = PatranPCL('../../CADAssembly.xml', '../../CADAssembly_metrics.xml', '../../ComputedValues.xml')
            ppcl.create_pcl_input_file(copy_xml_text=False)

        except Exception:
            msg = "Exception with CreatPatranInputFile/PatranPCL"
            self.logger.error(msg)
            self.logger.error("- Is it in {}?".format(os.path.join('META', 'bin', 'CAD')))
            cad_library.exitwitherror(msg, 99)

        # python_command = " {} {} {} {} {}".format(
        #     cpif_path,
        #     '-cadassembly ../../CADAssembly.xml',
        #     '-cadassembly_metrics ../../CADAssembly_metrics.xml',
        #     '-computedvalues ../../ComputedValues.xml',
        #     '-copyxmltext False'
        # )
        #
        # subprocess_cmd = "'{}'{}".format(sys.executable, python_command)
        #
        # self.logger.info("Calling {}.".format(subprocess_cmd))
        #
        # cpif_result = self.call_subprocess(subprocess_cmd)
        # # cpif_result = self.popen_subprocess(sys.executable + python_command, "CreatePatranInput")
        #
        # if cpif_result != 0:
        #     if cpif_result == 99:
        #         msg = 'CreatePatranInputFile.py failed; see {}.'.format(os.path.join(patran_nastran_dir, '_FAILED.txt'))
        #         self.logger.error(msg)
        #         cad_library.exitwitherror(msg, -1)
        #     else:
        #         os.chdir(result_dir)
        #         msg = 'CADJobDriver.run_patran_nastran() failed; try debugging directly.'
        #         cad_library.exitwitherror(msg, -1)

        self.logger.info("CreatePatranModelInput.txt is created.")

        pcl_input_name = 'CreatePatranModelInput.txt'
        pcl_name = 'CreatePatranModel.pcl'
        ses_name = 'CreatePatranModel.ses'
        # ses_path = r"D:\\BLADE\\meta-blademda\\bin\\CAD\\CreatePatranModel\\CreatePatranModel.ses"

        pcl_path = os.path.join(meta_src_cad_python, pcl_name)
        if not os.path.exists(pcl_path):
            pcl_path = os.path.join(meta_bin_cad, pcl_name)
            if not os.path.exists(pcl_path):
                cad_library.exitwitherror("Could not find {} ({}).".format(pcl_name, pcl_path), -1)

        ses_path = os.path.join(meta_src_cad_python, ses_name)
        if not os.path.exists(ses_path):
            ses_path = os.path.join(meta_bin_cad, ses_name)
            if not os.path.exists(ses_path):
                cad_library.exitwitherror("Could not find {} ({}).".format(ses_name, ses_path), -1)

        try:
            shutil.copy2(pcl_path, patran_nastran_dir)
            shutil.copy2(ses_path, patran_nastran_dir)

        except Exception:
            msg = "Could not find {} and/or {}".format(pcl_path, ses_path)
            self.logger.error(msg)
            cad_library.exitwitherror(msg, -1)

        pcl_command = "patran -b -graphics -sfp {} -stdout CreatePatranModel_Session.log".format(ses_name)

        with open('RunPatranNastran.cmd', 'wb') as cmd_file_out:
            cmd_file_out.write(pcl_command)

        if os.path.exists(pcl_input_name) and os.path.exists(pcl_name) and os.path.exists(ses_path):
            patran_nastran_result = self.call_subprocess(pcl_command)
            # patran_nastran_result = self.popen_subprocess(pcl_command, 'CreatePatranModel')

        self.logger.info("Skipping Post-Processing")

        #     if patran_nastran_result != 0:
        #         msg = "Patran/Nastran failed in {}: '{}'".format(patran_nastran_dir, pcl_command)
        #
        #         if os.path.exists('log'):
        #             with open(os.path.join('log', '_PATRAN_NASTRAN_FAILED.txt'), 'wb') as f_out:
        #                 f_out.write(msg)
        #
        #         cad_library.exitwitherror(msg, -1)
        #
        #     else:
        #         patran_pp_name = 'Patran_PP.py'
        #
        #         if not os.path.isfile(os.path.join(meta_bin_cad, patran_pp_name)):
        #             cad_library.exitwitherror(
        #                 'Can\'t find {}. Do you have the META toolchain installed properly?',format(patran_pp_name), -1)
        #
        #         post_processing_args = "{} {} {} {} {}".format(
        #             "Nastran_mod.bdf",
        #             "Nastran_mod.xdb",
        #             "..\\AnalysisMetaData.xml",
        #             "..\\..\\RequestedMetrics.xml",
        #             "..\\..\\testbench_manifest.json"
        #         )
        #
        #         # print(post_processing_args)
        #
        #         with open('RunPostProcessing.cmd', 'wb') as cmd_file_out:
        #             meta_python_path = os.path.join('%MetaPath%', 'bin', 'Python27', 'Scripts', 'Python.exe')
        #             patran_pp_path = os.path.join('bin', 'CAD', patran_pp_name)
        #             cmd_text = '{} {} {}'.format(
        #                 meta_python_path, os.path.join('%MetaPath%', patran_pp_path), post_processing_args)
        #             cmd_file_out.write(cmd_text)
        #
        #         print("Starting {}...".format('Patran_PP'))
        #
        #         pp_command = "{} {} {}".format(sys.executable,
        #                                        os.path.join(meta_bin_cad, patran_pp_name),
        #                                        post_processing_args)
        #
        #         if self.run_pp:
        #             self.call_subprocess(pp_command)
        #
        # else:
        #     msg = "Could not find {}, {}, or {}.".format(pcl_input_name, pcl_name, ses_path)
        #     cad_library.exitwitherror(msg, -1)

    def popen_subprocess(self, command, log_name_no_extension=None):

        subprocess_command = command
        working_dir = os.getcwd()
        time_stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if log_name_no_extension is None:
            log_file_name = "()_{}.txt".format(get_function_name(), time_stamp)
        else:
            log_file_name = "{}_{}.txt".format(log_name_no_extension, time_stamp)

        self.logger.info("Calling {} from working directory {}...".format(subprocess_command, working_dir))

        if not os.path.exists('log'):
            os.makedirs('log')

        return_code = -42

        with open(os.path.join('log', log_file_name), 'wb') as lims_log:
            subprocess_popen = subprocess.Popen(subprocess_command, stdout=lims_log, cwd=working_dir)
            # subprocess_popen = subprocess.Popen(subprocess_command, stdout=subprocess.PIPE, cwd=working_dir)

            # subprocess_log = ""
            # for line in subprocess_popen.stdout:
            #     subprocess_log += line + '\n'

            subprocess_popen.wait()
            lims_log.flush()
            return_code = subprocess_popen.returncode

            # lims_log.writelines(subprocess_log)

        if return_code != 0:
            msg = "Subprocess.Popen {} failed: {}".format(subprocess_command, subprocess_popen.returncode)
            self.logger.error(msg)

        return return_code

    def run_nastran(self):
        os.chdir(os.getcwd() + '\\Analysis\\Nastran')

        nastran_py_cmd = ' \"' + cad_library.META_PATH + 'bin\\CAD\Nastran.py\" ..\\Nastran_mod.nas'

        self.call_subprocess(sys.executable + nastran_py_cmd)

        patranscript = cad_library.META_PATH + 'bin\\CAD\\Patran_PP.py'

        if not os.path.isfile(patranscript):
            msg = 'Can\'t find ' + patranscript + '. Do you have the META toolchain installed properly?'
            cad_library.exitwitherror(msg, -1)

        nas_path = '..\\Nastran_mod.nas'
        xdb_path = 'Nastran_mod.xdb'
        meta_data = '..\\AnalysisMetaData.xml'
        req_metrics = '..\\..\\RequestedMetrics.xml'
        tb_manifest = '..\\..\\testbench_manifest.json'

        patran_script_cmd = ' \"{}\" {} {} {} {} {}'\
            .format(patranscript, nas_path, xdb_path, meta_data, req_metrics, tb_manifest)

        self.call_subprocess(sys.executable + patran_script_cmd)

    def run_calculix(self):
        isisext = os.environ['PROE_ISIS_EXTENSIONS']
        os.chdir(os.getcwd() + "\\Analysis\\Calculix")
        if isisext is None:
            cad_library.exitwitherror ('PROE_ISIS_EXTENSIONS env. variable is not set. Do you have the META toolchain installed properly?', -1)
        deckconvexe = os.path.join(isisext,'bin','DeckConverter.exe')
        self.call_subprocess(deckconvexe + ' -i ..\\Nastran_mod.nas')
        with _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, r'Software\CMS\CalculiX', 0,
                         _winreg.KEY_READ | _winreg.KEY_WOW64_32KEY) as key:
            bconvergedpath = _winreg.QueryValueEx(key, 'InstallLocation')[0]
        self.call_subprocess(bconvergedpath+'\\CalculiX\\bin\\ccx.bat -i ..\\Nastran_mod')
        metapython = os.path.join(cad_library.META_PATH, 'bin', 'Python27', 'Scripts', 'python.exe')
        calculix_pp = os.path.join(cad_library.META_PATH, 'bin', 'CAD', 'ProcessCalculix.py')
        self.call_subprocess(metapython + " " + calculix_pp + " -o ..\\Nastran_mod.frd -p ..\\AnalysisMetaData.xml -m ..\\..\\RequestedMetrics.xml -j ..\\..\\testbench_manifest.json -e PSolid_Element_Map.csv")


def main():

    # create file handler which logs even debug messages
    log_path = 'log'

    if not os.path.isdir(log_path):
        os.mkdir(log_path)

    logger = logging.getLogger('CADJobDriver')
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(os.path.join(log_path, 'CADJobDriver.py.txt'), 'w')
    formatter = logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    global args

    parser = argparse.ArgumentParser(description='Executes a CAD or FEA job. Invokes the specified assembler, mesher and analyzer in this sequence.')
    parser.add_argument('-assembler', choices=['CREO']);
    parser.add_argument('-mesher', choices=['NONE','CREO','ABAQUS','PATRAN','ABAQUSMDLCHECK','GMESH']);
    parser.add_argument('-analyzer', choices=['NONE','ABAQUSMODEL','ABAQUSDECK','NASTRAN','CALCULIX', 'PATRAN_NASTRAN']);
    parser.add_argument('-mode', choices=['STATIC','MODAL','DYNIMPL','DYNEXPL']);
    args = parser.parse_args()

    cad_job_driver = CADJobDriver(args.assembler, args.mesher, args.analyzer, args.mode)
    # cad_job_driver = CADJobDriver('ASSEMBLY_EXISTS', args.mesher, args.analyzer, args.mode, False)
    # cad_job_driver = CADJobDriver(args.assembler, args.mesher, args.analyzer, args.mode, False)


if __name__ == '__main__':
    main()
