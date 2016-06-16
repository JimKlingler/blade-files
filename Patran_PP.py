import sys
import argparse
import shutil
from subprocess import call
import os
# from xml.etree.ElementTree import Element, SubElement, ElementTree, Comment
import ComputedMetricsSummary
import UpdateReportJson_CAD
import logging
import csv
import _winreg


def recurselist(component, componentList):
    for comp in componentList.values():
        if component.ComponentID in comp.Children and not comp.IsConfigurationID:
            if len(comp.MetricsInfo.keys()) == 0:
                recurselist(comp, componentList)
            else:
                component.MetricsInfo = comp.MetricsInfo

def ParseOutFile(outfilename, gComponentList):
    ##Format##
    mtype = 0
    lcase = 1
    part  = 2
    value = 3
    ##########
    ifile = open(outfilename)
    reader = csv.reader(ifile)
    for row in reader:
        for component in gComponentList:
            # MetaData : PSOLID_3 || PatranOutput : PSOLID.3
            eID = '.'.join(gComponentList[component].ElementID.rsplit('_', 1)).lower()
            if eID == row[part].lower():
                gComponentList[component].FEAResults[row[mtype]] = float(row[value])


class Patran_PostProcess:

    def __init__(self, args, patran_path):
        self._args = args
        self._logger = logging.getLogger('root.Patran_PostProcess')
        filename = args.xdb_filename.split(".")[0]
        self._filename = filename.replace("_nas_mod","")
        self._lib_file_name = 'patran_pp.pcl'
        self._bdf_file_name = filename + ".bdf"

        if args.nas_filename != self._bdf_file_name:
            shutil.copy2(args.nas_filename, self._bdf_file_name)

        self._xdb_file_name = args.xdb_filename
        self._patran_path = patran_path

    def pre_process_cleanup(self):
        db_name = self._filename + ".db"
        out_txt_name = self._filename + "_out.txt"

        if os.path.exists(db_name):
            os.remove(db_name)
        if os.path.exists(out_txt_name):
            os.remove(out_txt_name)

    def create_session_file(self):
        logger.debug("Filename: {}".format(self._filename))

        new_line = '\n'

        with open(self._filename + "_PP.ses", "w") as ses_out:
            ses_out.write("!!compile {} into patran_pp.plb{}".format(self._lib_file_name, new_line))
            ses_out.write("!!library patran_pp.plb{}".format(new_line))
            ses_out.write("STRING dir[262] = '.\\'{}".format(new_line))
            ses_out.write("STRING filename[64] = '{}'{}".format(self._filename, new_line))
            ses_out.write("STRING bdfPath[262] = '{}'{}".format(self._bdf_file_name, new_line))
            ses_out.write("STRING xdbPath[262] = '{}'{}".format(self._xdb_file_name, new_line))
            ses_out.write("Patran_PP(patranDir, dir, filename, bdfPath, xdbPath)")

    def run_patran(self):

        status = True
        self.create_session_file()
        self.pre_process_cleanup()

        patran_call = "patran -b -graphics -sfp {}_PP.ses -stdout {}_PP_log.txt".format(self._filename, self._filename)

        retcode = call(patran_call, shell=True)

        if retcode == 0:
            logger.info("Patran Process Successful!!")
        else:
            status = False
            logger.error("Patran Process Failed!")

        return status

    def update_results_files(self):
        status = True
        gComponentList = ComputedMetricsSummary.ParseMetaDataFile(args.MetaDataFile, None, None)

        if not os.path.exists(self._filename + "_out.txt"):
            msg = "File not found: {}".format(self._filename + "_out.txt")
            logger.error(msg)
            

        ParseOutFile(self._filename + "_out.txt", gComponentList)
        reqMetrics = ComputedMetricsSummary.ParseReqMetricsFile(args.RequestedMetrics, gComponentList)
        
        for component in gComponentList.values():
            recurselist(component, gComponentList)

        for component in gComponentList.values():
            for comp in gComponentList.values():
                if component.ComponentID in comp.Children and not comp.IsConfigurationID:
                    # component is actually a child, so parent's metric data
                    # should be updated - provided that child metrics are larger
                    logger.debug(comp)
                    if 'FactorOfSafety' in component.MetricsInfo:
                        component.MetricsInfo['FactorOfSafety'] = comp.MetricsInfo['FactorOfSafety']
                    if 'VonMisesStress' in component.MetricsInfo:
                        component.MetricsInfo['VonMisesStress'] = comp.MetricsInfo['VonMisesStress']
                    break
                
            if component.CadType == "PART":
                fos = float(component.Allowables.mechanical__strength_tensile) / component.FEAResults["VM"]
                #fos = float(component.MaterialProperty['Mises'])  / component.FEAResults["VM"]
                component.FEAResults['FOS'] = fos
                if 'FactorOfSafety' in component.MetricsInfo:
                    component.MetricsOutput[component.MetricsInfo['FactorOfSafety']] = fos
                if 'VonMisesStress' in component.MetricsInfo:
                    component.MetricsOutput[component.MetricsInfo['VonMisesStress']] = component.FEAResults["VM"]
        
        ################  CSV  ###############################
        with open(self._filename + '.csv', 'wb') as f:
            writer = csv.writer(f)
            writer.writerow(["Unique ID","Allowable Stress","Maximum Stress","Factor of Safety"])
            for component in gComponentList.values():
                if component.CadType == "PART":
                    writer.writerow([component.ComponentID,
                                     str(component.Allowables.mechanical__strength_tensile), \
                                     str(component.FEAResults["VM"]),str(component.FEAResults["FOS"])])
                    
        ################  Populate Assembly Results  #########
        for component in gComponentList.values():
            logger.info('ComponentID: {}'.format(component.ComponentID))
            logger.info(component)
            logger.info('')
            if component.CadType == "ASSEMBLY" and not component.IsConfigurationID:
                FOS = []
                VM = []
                for part in component.Children:
                    FOS.append(gComponentList[part].FEAResults["FOS"])
                    VM.append(gComponentList[part].FEAResults["VM"])
                component.FEAResults["FOS"] = min(FOS)
                component.FEAResults["VM"] = max(VM)
                component.MetricsOutput[component.MetricsInfo['FactorOfSafety']] = min(FOS)
                component.MetricsOutput[component.MetricsInfo['VonMisesStress']] = max(VM)


        ################  Populate Metrics  #################
        computedValuesXml = ComputedMetricsSummary.WriteXMLFile(gComponentList)
        
        ################  Update Results Json  ##############
        if os.path.exists(args.ResultsJson):
            UpdateReportJson_CAD.update_manifest(args.ResultsJson, computedValuesXml)
        else:
            logger.error("Could not update file: {}, file does not exist.".format(args.ResultsJson))
            status = False

        logger.info("Post Processing Complete, CSV and metrics updated")

        return status


if __name__ == '__main__':

    logger = logging.getLogger('root.Patran_PostProcess')
    handler = logging.FileHandler('PostProcess_Log.txt', 'w')
    formatter = logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    try:
        parser = argparse.ArgumentParser(description='Post process Nastran output w/ Patran')
        parser.add_argument('nas_filename', help='.nas File Name')
        parser.add_argument('xdb_filename', help='.xdb File Name')
        parser.add_argument('MetaDataFile', help='.xml AnalysisMetaData File Name')
        parser.add_argument('RequestedMetrics', help='.xml RequestedMetrics File name')
        parser.add_argument('ResultsJson', help='.json summary testresults File name')
        args = parser.parse_args()

        if not os.path.exists(args.nas_filename):
            msg = "File not found: {}".format(args.nas_filename)
            logger.error(msg)

        if not os.path.exists(args.xdb_filename):
            msg = "File not found: {}".format(args.xdb_filename)
            logger.error(msg)

        if not os.path.exists(args.MetaDataFile):
            msg = "File not found: {}".format(args.MetaDataFile)
            logger.error(msg)

        if not os.path.exists(args.RequestedMetrics):
            msg = "File not found: {}".format(args.RequestedMetrics)
            logger.error(msg)

        with _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE,
                             r'Software\META',
                             0,
                             _winreg.KEY_READ | _winreg.KEY_WOW64_32KEY) as key:
            META_PATH = _winreg.QueryValueEx(key, 'META_PATH')[0]

        ppDir = os.path.join(META_PATH, 'bin', 'CAD')

        with _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE,
                             r'Software\Wow6432Node\MSC.Software Corporation\Patran x64\Latest',
                             0,
                             _winreg.KEY_READ | _winreg.KEY_WOW64_32KEY) as key:

            LATEST_PATRAN_VERSION = _winreg.QueryValueEx(key, '')[0]

        with _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE,
                             r'Software\Wow6432Node\MSC.Software Corporation\Patran x64\\' + LATEST_PATRAN_VERSION,
                             0,
                             _winreg.KEY_READ | _winreg.KEY_WOW64_32KEY) as key:

            PATRAN_PATH = _winreg.QueryValueEx(key, 'Path')[0]

        LIB_FILE_NAME = 'patran_pp.pcl'

        if not os.path.exists(os.path.join(ppDir, LIB_FILE_NAME)):
            msg = "File not found in Meta-Tools installation: {}".format(LIB_FILE_NAME)
            logger.error()
            sys.exit(1)

        shutil.copy2(os.path.join(ppDir, LIB_FILE_NAME), os.getcwd())
        
        post_process = Patran_PostProcess(args, PATRAN_PATH)

        success = post_process.run_patran()

        if not success:
            logger.error("post_process.run_patran() returned false")
            sys.exit(1)

        success = post_process.update_results_files()

        if not success:
            logger.error("post_process.update_results_files() returned false")
            sys.exit(1)

    except: # catch *all* exceptions
        import traceback
        e = sys.exc_info()[0]
        var = traceback.format_exc()
        msg = "Exception: {}".format(var)
        logger.error(msg)
        sys.exit(1)

