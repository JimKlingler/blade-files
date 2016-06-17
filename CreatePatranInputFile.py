__author__ = 'James Klingler'

import os
import sys
from lxml import etree as letree
import inspect
import json
import string
import argparse
import logging
import cad_library
import datetime


def line_number_as_pcl_comment():
    msg = "  # CreatePatranInputFile.py line: {}".format(inspect.currentframe().f_back.f_lineno)
    return msg


def line_number_of_problem():
    msg = "Problem at line: {}".format(inspect.currentframe().f_back.f_lineno)
    return msg


def is_float(string_value):
    try:
        float(string_value)
        return True
    except ValueError:
        return False


def remove_lines_with_none(block_string):

    split_lines = block_string.split('\n')
    new_lines = []
    removed_lines = []

    for line in split_lines:
        if '= None' in line:
            removed_lines.append(line)
        else:
            new_lines.append(line)

    new_string = '\n'.join(new_lines)
    removed_string = '\n'.join(removed_lines)

    return new_string, removed_string


class PatranPCL():

    def __init__(self, cad_assembly_path='CADAssembly.xml',
                 cad_assembly_metrics_path='CADAssembly_metrics.xml',
                 computed_values_path='ComputedValues.xml'):

        self.get_logger()
        self.bin_cad_dir = os.path.dirname(os.path.realpath(__file__))

        self.patran_input_file_name = 'CreatePatranModelInput.txt'

        # TODO: Di please review
        self.patran_input_template_path = os.path.join(self.bin_cad_dir, 'PatranInputTemplate.json')

        self.pcl_globals = {
            'Surface_Contents_Position': "000{}".format(line_number_as_pcl_comment()),
            'Surface_Contents_Offset_Value': "000{}".format(line_number_as_pcl_comment()),
            'Surface_Element_Type': "000{}".format(line_number_as_pcl_comment()),
            'Surface_Mesh_Parameters_ID': '1{}'.format(line_number_as_pcl_comment()),
            'Test_Bench_Name': 'A_horse_with_no_name{}'.format(line_number_as_pcl_comment())
        }

        if not os.path.exists(computed_values_path):
            self.failure("ComputedValues.xml not found at '{}'".format(os.path.abspath(computed_values_path)))

        self.cv_metrics_by_id = self.get_metrics_from_computed_values(computed_values_path)

        if not os.path.exists(cad_assembly_metrics_path):
            self.failure("CADAssembly_metrics.xml not found at '{}'".format(os.path.abspath(cad_assembly_metrics_path)))

        self.cam_materials_by_comp_id = self.get_materials_from_ca_metrics(cad_assembly_metrics_path)

        # Get the example Material Library
        meta_path = os.environ.get('MetaPath')  # this is set in the runCADJob.bat; if not, set it here
        if meta_path is None:
            meta_path = os.path.abspath(os.path.join(self.bin_cad_dir, '..', '..'))

        self.logger.info('%MetaPath% = {}'.format(meta_path))

        self.material_library_path = os.path.join(meta_path, 'models', 'MaterialLibrary', 'material_library.json')
        self.material_library = {}

        if not os.path.exists(self.material_library_path):
            self.material_library_path = os.path.join('C:', 'Users', 'Public', 'Documents', 'META Documents',
                                                      'MaterialLibrary', 'material_library.json')

            if not os.path.exists(self.material_library_path):
                abs_path = os.path.abspath(self.material_library_path)
                self.failure("Material library path invalid: {} ({})".format(abs_path, line_number_of_problem()))

        with open(self.material_library_path, 'r') as file_in:
            material_library = json.load(file_in)
            self.material_library = material_library["Material library"]

        # Read in the PCL template
        self.pcl_template_json = {}

        if not os.path.exists(self.patran_input_template_path):
            self.failure("Patran input template.json not found: {}".format(self.patran_input_template_path))

        with open(self.patran_input_template_path, 'r') as file_in:
            self.pcl_template_json = json.load(file_in)

        self.is_surface_model = False
        self.solids = {}

        self.points_by_metric_id = {}
        self.geometries_by_metric_id = {}
        self.surfaces_by_metric_id = {}
        self.constraint_specifiers = {
            'Displacement': {},
            'Pin': {}
        }
        self.constraints_by_id = {}
        self.mesh_parameters = {}
        self.solver_node = None
        self.analysis = {}
        self.layups = {}
        self.layers = {}
        self.surface_contents = {}
        self.materials = {}
        self.loads = {}
        self.load_values = {
            'Scalar': {},
            'Vector': {}
        }

        if not os.path.exists(cad_assembly_path):
            self.failure("CADAssembly.xml not found at '{}'.".format(os.path.abspath(cad_assembly_path)))

        cad_assm_tree = letree.parse(cad_assembly_path)

        self.cad_assm_root = cad_assm_tree.getroot()

        self.get_assembly_name()

        self.get_points()
        self.get_geometries()
        self.get_component_materials()
        if self.is_surface_model:
            self.get_surfaces()
        self.get_constraint_specifiers()
        self.get_mesh_parameters()
        self.get_analysis()
        #self.get_surface_contents()
        self.get_loads()

    def get_logger(self):

        # create logger with 'spam_application'
        self.logger = logging.getLogger('PatranPCL')
        self.logger.setLevel(logging.DEBUG)

        # create file handler which logs even debug messages
        if not os.path.isdir('log'):
            os.mkdir('log')

        fh = logging.FileHandler(os.path.join('log', 'CreatePatranInputFile.py.log'))
        fh.setLevel(logging.DEBUG)

        # create console handler with a higher log level
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)

        # create formatter and add it to the handlers
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        # add the handlers to the logger
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

        self.logger.info("=======================================")
        self.logger.info("New CreatePatranInputFile.py execution.")
        self.logger.info("=======================================")

    def failure(self, failure_message=None):

        if failure_message is None:
            failure_message = line_number_of_problem()
        else:
            failure_message += ' ({})'.format(line_number_of_problem())

        self.logger.error(failure_message)

        with open("_FAILED.txt", 'w') as f_out:
            f_out.writelines(failure_message)

        sys.exit(99)

    def get_metrics_from_computed_values(self, cv_path):

        try:
            cv_metrics_by_id = {}

            cv_tree = letree.parse(cv_path)
            cv_root = cv_tree.getroot()

            metric_string = "Component/Metrics/Metric[@Type='VECTOR']"
            self.logger.info("Searching for {} ".format(metric_string))
            metric_nodes = cv_root.findall(metric_string)

            for node in metric_nodes:
                metric_id = node.attrib['MetricID']
                units = node.attrib['Units']
                array_value = node.attrib['ArrayValue']
                x_y_z = array_value.split(';')

                xml_node_text = letree.tostring(node)

                cv_metrics_by_id[metric_id] = {
                    'ID': '000',
                    'x_Cord': x_y_z[0],
                    'y_Cord': x_y_z[1],
                    'z_Cord': x_y_z[2],
                    'Comments': '(Units={};MetricID={})'.format(units, metric_id),
                    'XML_Text': xml_node_text
                }

            return cv_metrics_by_id

        except Exception as xml_exception:
            self.failure("Failed to get metrics from ComputedValues: '{}'".format(xml_exception.msg))

    def get_materials_from_ca_metrics(self, cam_path):

        materials_by_id = {}

        cam_tree = letree.parse(cam_path)
        cam_root = cam_tree.getroot()

        cad_component_string = ".//CADComponent[@MetricID='{}']"

        metric_comp_string = "MetricComponents/MetricComponent[@Type='PART']"
        self.logger.info("Searching for {} ".format(metric_comp_string))
        metric_comp_nodes = cam_root.findall(metric_comp_string)

        for mc_node in metric_comp_nodes:
            metric_id = mc_node.attrib['MetricID']
            name = mc_node.attrib['Name']

            material_node = mc_node.find("Material")
            material_type = material_node.attrib['Type']

            linked_cad_component_string = cad_component_string.format(metric_id)
            cad_component_node = cam_root.find(linked_cad_component_string)

            comp_instance_id = cad_component_node.attrib['ComponentInstanceID']

            materials_by_id[comp_instance_id] = material_type

        return materials_by_id

    def get_points(self):

        metric_string = "Assembly/Analyses/Static/Metrics/Metric[@MetricType='POINTCOORDINATES']"
        self.logger.info("Searching for {} ".format(metric_string))
        metrics_for_points = self.cad_assm_root.findall(metric_string)

        id_counter = 1

        for metric_node in metrics_for_points:
            metric_id = metric_node.attrib['MetricID']
            point_details = self.cv_metrics_by_id[metric_id]
            point_details['ID'] = str(id_counter)

            self.points_by_metric_id[metric_id] = point_details

            id_counter += 1

    def get_geometries(self):

        features_string = ".//Geometry/Features[@GeometryType='FACE'][@FeatureGeometryType='POINT']"
        self.logger.info("Searching for {} ".format(features_string))
        features = self.cad_assm_root.findall(features_string)

        id_counter = 1

        for features_element in features:
            feature_element = features_element.find("Feature")
            metric_id = feature_element.attrib.get('MetricID')

            # TODO Multiple Geometries with the same MetricID and same Point?
            if metric_id in self.geometries_by_metric_id:
                continue

            xml_node_text = letree.tostring(feature_element)

            self.geometries_by_metric_id[metric_id] = {
                'ID': str(id_counter),
                'Type': 'FACE',
                'Point_ID': self.points_by_metric_id[metric_id]['ID'],  # get point id from metric id
                'Comments': '(MetricID={})'.format(metric_id),
                'XML_Text': xml_node_text
            }

            id_counter += 1

    def get_surfaces(self):

        surfaces_string = ".//Geometry/Features[@GeometryType='FACE']"
        self.logger.info("Searching for {} ".format(surfaces_string))
        features_for_surfaces = self.cad_assm_root.findall(surfaces_string)

        id_counter = 1

        for features_element in features_for_surfaces:
            feature_element = features_element.find("Feature")
            metric_id = feature_element.attrib.get('MetricID')

            existing_surface = self.surfaces_by_metric_id.get(metric_id, None)

            if existing_surface is None:

                xml_node_text = letree.tostring(feature_element)

                surface = {
                    'Comments': "(MetricID={})".format(metric_id),
                    'XML_Text': xml_node_text,
                    'ID': id_counter,
                    'Geometry_ID': self.geometries_by_metric_id[metric_id]['ID'],  # get Geometry_ID based on MetricID
                    'Element_Type': '$Surface_Element_Type',
                    'Mesh_Parameters_ID': '$Surface_Mesh_Parameters_ID'
                }

                self.surfaces_by_metric_id[metric_id] = surface

                id_counter += 1

    def get_constraint_specifiers(self):

        analysis_constraint_string = "Assembly/Analyses/FEA/AnalysisConstraints/AnalysisConstraint/"

        pin_string = "Pin"
        displacement_string = "Displacement"

        id_counter = 1

        self.logger.info("Searching for {} ".format(analysis_constraint_string + pin_string))
        pin_nodes = self.cad_assm_root.findall(analysis_constraint_string + pin_string)

        for p_node in pin_nodes:

            xml_node_text = letree.tostring(p_node)

            constraint_specifier = {
                'ID': str(id_counter),
                'Comments': "CadAssembly _id:{}".format(p_node.attrib['_id']),
                'XML_Text': xml_node_text
            }

            for child in p_node:
                constraint_specifier[child.tag] = child.attrib['Property']

            self.constraint_specifiers[pin_string][id_counter] = constraint_specifier

            id_counter += 1

        self.logger.info("Searching for {} ".format(analysis_constraint_string + displacement_string))
        displacement_nodes = self.cad_assm_root.findall(analysis_constraint_string + displacement_string)

        for d_node in displacement_nodes:
            comment = "CadAssembly _id:{}".format(d_node.attrib['_id'])
            xml_node_text = letree.tostring(d_node)

            constraint_specifier = {
                'Comments': "",
                'ID': str(id_counter)
            }

            for child in d_node:
                if child.tag == 'Translation':
                    x = child.attrib['x']
                    y = child.attrib['y']
                    z = child.attrib['z']

                    if x is not None:
                        if is_float(x):
                            constraint_specifier['x_Disp_Val'] = x
                            constraint_specifier['x_Disp_State'] = None
                        elif x == 'FIXED' or x == 'FREE':
                            constraint_specifier['x_Disp_State'] = x
                            constraint_specifier['x_Disp_Val'] = None
                        else:
                            self.failure("Problem: 'x' value for Displacement node {}".format(d_node.attrib['_id']))
                    else:
                        self.failure("'x' value for Displacement node {} is 'None'".format(d_node.attrib['_id']))

                    if y is not None:
                        if is_float(y):
                            constraint_specifier['y_Disp_Val'] = y
                            constraint_specifier['y_Disp_State'] = None
                        elif y == 'FIXED' or y == 'FREE':
                            constraint_specifier['y_Disp_State'] = y
                            constraint_specifier['y_Disp_Val'] = None
                        else:
                            self.failure("Problem: 'y' value for Displacement node {}".format(d_node.attrib['_id']))
                    else:
                        self.failure("'y' value for Displacement node {} is 'None'".format(d_node.attrib['_id']))

                    if z is not None:
                        if is_float(z):
                            constraint_specifier['z_Disp_Val'] = z
                            constraint_specifier['z_Disp_State'] = None
                        elif z == 'FIXED' or z == 'FREE':  # TODO actually check the string value 'elif'
                            constraint_specifier['z_Disp_State'] = z
                            constraint_specifier['z_Disp_Val'] = None
                        else:
                            self.failure("Problem: 'z' value for Displacement node {}".format(d_node.attrib['_id']))
                    else:
                        self.failure("'z' value for Displacement node {} is 'None'".format(d_node.attrib['_id']))

                    comment += "; Translation Units:\'{}\'".format(child.attrib['Units'])

                elif child.tag == 'Rotation':
                    x = child.attrib['x']
                    y = child.attrib['y']
                    z = child.attrib['z']

                    if x is not None:
                        if is_float(x):
                            constraint_specifier['x_Rot_Val'] = x
                            constraint_specifier['x_Rot_State'] = None
                        elif x == 'FIXED' or x == 'FREE':
                            constraint_specifier['x_Rot_State'] = x
                            constraint_specifier['x_Rot_Val'] = None
                        else:
                            self.failure("Problem: 'x' value for Displacement node {}".format(d_node.attrib['_id']))
                    else:
                        self.failure("'x' value for Displacement node {} is 'None'".format(d_node.attrib['_id']))

                    if y is not None:
                        if is_float(y):
                            constraint_specifier['y_Rot_Val'] = y
                            constraint_specifier['y_Rot_State'] = None
                        elif y == 'FIXED' or y == 'FREE':
                            constraint_specifier['y_Rot_State'] = y
                            constraint_specifier['y_Rot_Val'] = None
                        else:
                            self.failure("Problem: 'y' value for Displacement node {}".format(d_node.attrib['_id']))
                    else:
                        self.failure("'y' value for Displacement node {} is 'None'".format(d_node.attrib['_id']))

                    if z is not None:
                        if is_float(z):
                            constraint_specifier['z_Rot_Val'] = z
                            constraint_specifier['z_Rot_State'] = None
                        elif z == 'FIXED' or z == 'FREE':
                            constraint_specifier['z_Rot_State'] = z
                            constraint_specifier['z_Rot_Val'] = None
                        else:
                            self.failure("Problem: 'z' value for Displacement node {}".format(d_node.attrib['_id']))
                    else:
                        self.failure("'z' value for Displacement node {} is 'None'".format(d_node.attrib['_id']))

                    comment += "; Rotation Units:\'{}\'".format(child.attrib['Units'])

            constraint_specifier['Comments'] = comment
            constraint_specifier['XML_Text'] = xml_node_text

            self.constraint_specifiers[displacement_string][id_counter] = constraint_specifier

            self.get_constraint(str(id_counter), d_node)

            id_counter += 1

    def get_constraint(self, displacement_id, displacement_constraint_node):

        #  TODO we can only handle 'Displacement' at the moment (6/3/16)

        analysis_constraint_node = displacement_constraint_node.getparent()

        # TODO this will not work for CADAssembly_01, there may be more than 1 feature
        feature_node = analysis_constraint_node.find('Geometry/Features/Feature')

        xml_node_text = letree.tostring(feature_node)

        metric_id = feature_node.attrib['MetricID']
        geometry_id = self.geometries_by_metric_id[metric_id]['ID']

        id_counter = len(self.constraints_by_id)
        id_counter += 1

        constraint = {
            'ID': str(id_counter),
            'Type': 'DISPLACEMENT{}'.format(line_number_as_pcl_comment()),
            'SubCase_ID': '1{}'.format(line_number_as_pcl_comment()),
            'Geometry_ID': geometry_id,
            'Displacement_ID': displacement_id,
            'Comments': "Feature Node _id:{}".format(feature_node.attrib['_id']),
            'XML_Text': xml_node_text
        }

        self.constraints_by_id[id_counter] = constraint

    def get_mesh_parameters(self):

        mesh_param_string = "Assembly/Analyses/FEA/MeshParameters"

        # First or default
        self.logger.info("Searching for {} ".format(mesh_param_string))
        mesh_params_list = self.cad_assm_root.findall(mesh_param_string)
        comment = '{}.'.format(mesh_param_string)

        max_global_length = '0.101{}'.format(line_number_as_pcl_comment())
        max_curv_delta = '0.102{}'.format(line_number_as_pcl_comment())
        ratio_min_to_max = '0.201{}'.format(line_number_as_pcl_comment())
        match_face_prox = '0.0501{}'.format(line_number_as_pcl_comment())
        xml_node_text = 'None'

        if len(mesh_params_list) == 0:

            warning_msg = "No MeshParameters node found in CADAssembly.xml; using hard-coded values"
            comment += '  ' + warning_msg
            self.logger.warning(warning_msg)

        if len(mesh_params_list) > 0:

            if len(mesh_params_list) > 1:
                comment += ' Multiple MeshParameters nodes.'

                for mp in mesh_params_list:
                    comment += "\n    #_id: {}".format(mp.attrib['_id'])

            self.pcl_globals['Surface_Mesh_Parameters_ID'] = "1{}".format(line_number_as_pcl_comment())

            mesh_params_node = mesh_params_list[0]
            xml_node_text = letree.tostring(mesh_params_node)

            max_global_length = mesh_params_node.attrib['Max_Global_Length']
            max_curv_delta = mesh_params_node.attrib['Max_Curv_Delta_Div_Edge_Len']
            ratio_min_to_max = mesh_params_node.attrib['Ratio_Min_Edge_To_Max_Edge']
            match_face_prox = mesh_params_node.attrib['Match_Face_Proximity_Tol']

        self.mesh_parameters = {
            'Comments': comment,
            'XML_Text': xml_node_text,
            'ID': "1{}".format(line_number_as_pcl_comment()),
            'Max_Global_Length': max_global_length,
            'Max_Curv_Delta_Div_Edge_Len': max_curv_delta,
            'Ratio_Min_Edge_To_Max_Edge': ratio_min_to_max,
            'Match_Face_Proximity_Tol': match_face_prox
        }

    def get_analysis(self):

        assembly_string = "Assembly"
        fea_analysis_string = "Assembly/Analyses/FEA"
        solver_string = fea_analysis_string + "/Solvers/Solver"

        assm_node = self.cad_assm_root.find(assembly_string)
        config_id = assm_node.attrib['ConfigurationID']

        fea_node = self.cad_assm_root.find(fea_analysis_string)
        fea_type = fea_node.attrib['Type']
        analysis_type = '101' if fea_type == 'STRUCTURAL' else '103'
        mesh_only = fea_node.attrib['MeshOnly']
        instructions = 'MESH_ONLY' if mesh_only == 'true' else 'MESH_AND_SOLVE'

        if self.solver_node is None:
            self.solver_node = self.cad_assm_root.find(solver_string)

        solver_type = self.solver_node.attrib['Type']
        if solver_type == 'PATRAN_NASTRAN':
            solver_type = 'NASTRAN  # PATRAN_NASTRAN in CADAssembly.xml'

        # While we are here... Get the shell_element_type and add it to pcl_global
        shell_element_type = self.solver_node.attrib['ShellElementType']
        if shell_element_type == "PLATE_4_NODE":
            self.pcl_globals['Surface_Element_Type'] = "QUAD4{}".format(line_number_as_pcl_comment())
        else:
            self.pcl_globals['Surface_Element_Type'] = "WHAT GOES HERE??".format(line_number_as_pcl_comment())

        xml_node_text = letree.tostring(fea_node)

        self.analysis = {
            'Configuration_ID': config_id,  # <Assembly ConfigurationID
            'Date': '{}'.format(datetime.datetime.now()),
            'Source_Model': '0101  # Hard-Coded',
            'Type': analysis_type,
            'Solver': solver_type,  # <Solver Type
            'Instructions': instructions,
            'Comments': "{}".format(line_number_as_pcl_comment()),
            'XML_Text': xml_node_text
        }

    def get_assembly_name(self):

        cad_assembly_string = ".//CADComponent[@Type='ASSEMBLY']"
        self.logger.info("Searching for {} ".format(cad_assembly_string))
        cad_assemblies = self.cad_assm_root.findall(cad_assembly_string)

        if len(cad_assemblies) == 1:
            cad_assembly = cad_assemblies[0]
            self.pcl_globals['Geometry_File_Name'] = cad_assembly.attrib['Name'] + "_asm.x_t"

    def get_component_materials(self):

        # CADComponent[@Type='ASSEMBLY'] should not have a Layup definition
        cad_component_parts_string = ".//CADComponent[@Type='PART']"
        self.logger.info("Searching for {} ".format(cad_component_parts_string))
        cad_components = self.cad_assm_root.findall(cad_component_parts_string)

        for cc in cad_components:
            cad_component_id = cc.attrib['ComponentID']

            material_layup_string = "Elements/Element/ElementContents/MaterialLayup"
            layup_node = cc.find(material_layup_string)
            element_string = "Elements/Element[@ElementType='SURFACE']"
            element_node = cc.find(element_string)

            if layup_node is None:  # TODO Solid model, not a surface.
                self.is_surface_model = False

                material_name = self.cam_materials_by_comp_id.get(cad_component_id, None)
                material_id = self.get_material_data(material_name)

                self.add_solid(material_id)

            else:
                self.get_layup(cad_component_id, layup_node)

                if element_node is not None:
                    self.get_surface_contents(cad_component_id, element_node)

    def add_solid(self, material_id):

        num_solids = len(self.solids.keys())
        solid_id = num_solids + 1

        solid = {
            'Comments': 'Element_Type is Hard-Coded; Only 1 Mesh_Parameters supported (6/1/2016).',
            'ID': solid_id,
            'Element_Type': 'TETRA10{}'.format(line_number_as_pcl_comment()),
            'Material_ID': material_id,
            'Mesh_Parameters_ID': '1  # "There can be only one."'
        }

        self.solids[solid_id] = solid

    def get_layup(self, cad_component_id, material_layup_node):

        layup_position = material_layup_node.attrib['Postion'] + line_number_as_pcl_comment()  # TODO Typo in 'Postion'
        layup_offset_value = material_layup_node.attrib['OffsetValue'] + line_number_as_pcl_comment()

        self.pcl_globals['Surface_Contents_Position'] = "{}{}".format(layup_position, line_number_as_pcl_comment())
        self.pcl_globals['Surface_Contents_Offset_Value'] = "{}{}".format(layup_offset_value, line_number_as_pcl_comment())

        self.logger.info("Searching for {} ".format("Layer"))
        layer_nodes = material_layup_node.findall("Layer")

        id_counter = len(self.layups)
        id_counter += 1

        layup_layer_ids = []

        for layer in layer_nodes:
            layer_id = layer.attrib['ID']
            material_name = layer.attrib['Material_Name']

            material_id = self.get_material_data(material_name)

            xml_node_text = letree.tostring(layer)

            layer = {
                'Comments': "CADComponent ID: {}, {}".format(cad_component_id, line_number_as_pcl_comment()),
                'XML_Text': xml_node_text,
                'ID': layer_id,
                'Material_ID': "{}  # {}".format(material_id, material_name),
                'Thickness': layer.attrib['Thickness'],
                'Orientation': layer.attrib['Orientation'],
                'Drop_Order': layer.attrib['Drop_Order']
            }

            index = cad_component_id + '_' + layer_id
            layup_layer_ids.append(index)
            self.layers[index] = layer

        self.layups[cad_component_id] = {
            'ID': id_counter,
            'LayerIDs': layup_layer_ids
        }

    def get_material_data(self, material_name):

        material = self.materials.get(material_name, None)

        if material is not None:
            return material['ID']

        data = self.material_library.get(material_name.lower(), None)

        if data is None:
            self.logger.error("Material lookup needs attention: {}".format(material_name))

        num_materials = len(self.materials.keys())
        material_id = num_materials + 1

        elastic_modulus_pa = data['mechanical__modulus_elastic']['value']
        try:
            elastic_modulus = elastic_modulus_pa/1000000.  # convert from Pa to MPa
        except ValueError:
            self.logger.warning("Could not convert Elastic Modulus to MPa: {}".format(line_number_of_problem()))
            elastic_modulus = '{}{}'.format(elastic_modulus_pa, line_number_as_pcl_comment())

        material = {
            'Comments': "{}{}".format
                (material_name, line_number_as_pcl_comment()),
            'ID': material_id,
            'Name': material_name,
            'Description': material_name,
            'Tropic_Type': 'ISOTROPIC{}'.format(
                line_number_as_pcl_comment()),
            'Elastic_Modulus': '{}{}'.format(
                elastic_modulus, line_number_as_pcl_comment()),
            'Poissons_Ratio': '{}{}'.format(
                data['mechanical__ratio_poissons']['value'], line_number_as_pcl_comment()),
            'Density': '{}{}'.format(
                data['density']['value'], line_number_as_pcl_comment()),
            'Therm_Expan_Coef': '{}{}'.format(
                data['thermal__coefficient_expansion_linear']['value'], line_number_as_pcl_comment())
        }

        self.materials[material_name] = material

        return material_id

    def get_surface_contents(self, cad_component_id, element_node):

        features_string = "Geometry/Features[@GeometryType='FACE'][@FeatureGeometryType='POINT']"
        features_node = element_node.find(features_string)

        feature_node = features_node.find("Feature")
        metric_id = feature_node.attrib.get('MetricID')

        surface = self.surfaces_by_metric_id.get(metric_id, None)
        surface_id = surface['ID'] if surface is not None else '000{}'.format(line_number_as_pcl_comment())

        layup_id = self.layups[cad_component_id]['ID']

        orientation_feature_string = "ElementContents/Orientation/Geometry/Features/Feature[@Name='{}']"

        # Get the 'Direction_Start_Pt' MetricID and get the associated point's ID
        start_point_string = "Direction_Start_Pt"
        start_point_node = element_node.find(orientation_feature_string.format(start_point_string))
        start_point_metric = start_point_node.attrib['MetricID']
        start_point = self.points_by_metric_id.get(
            start_point_metric, self.add_point(start_point_metric))
        start_point_id = start_point['ID']

        # Get the 'Direction_End_Pt' MetricID and get the associated point's ID
        end_point_string = "Direction_End_Pt"
        end_point_node = element_node.find(orientation_feature_string.format(end_point_string))
        end_point_metric = end_point_node.attrib['MetricID']
        end_point = self.points_by_metric_id.get(
            end_point_metric, self.add_point(end_point_metric))
        end_point_id = end_point['ID']

        id_counter = len(self.surface_contents)
        id_counter += 1

        xml_node_text = letree.tostring(feature_node)

        surface_contents = {
            'Comments': "This needs some attention.",
            'XML_Text': xml_node_text,
            'ID': "{}{}".format(id_counter, line_number_as_pcl_comment()),
            'Surface_ID': "{}{}".format(surface_id, line_number_as_pcl_comment()),
            'Material_Layup_ID': "{}{}".format(layup_id, line_number_as_pcl_comment()),
            'Direction_Start_Point_ID': "{}{}".format(start_point_id, line_number_as_pcl_comment()),
            'Direction_End_Point_ID': "{}{}".format(end_point_id, line_number_as_pcl_comment()),
            'Position': "$Surface_Contents_Position",
            'Offset_Value': "$Surface_Contents_Offset_Value"
        }

        self.surface_contents[id_counter] = surface_contents

    def add_point(self, metric_id):
        """This method should eventually be removed. It is
        here because of non-valid testing files, e.g.,
        CADAssembly, CADAssembly_metrics, ComputedValues"""

        id_counter = len(self.points_by_metric_id)
        id_counter += 1

        #point_details = self.cv_metrics_by_id[metric_id]
        point_details = self.cv_metrics_by_id.get(metric_id, None)
        if point_details is None:
            point_details = {
                'ID': id_counter,
                'x_Cord': 'X',
                'y_Cord': 'Y',
                'z_Cord': 'Z',
                'Comments': 'For MetricID:{};{}'.format(metric_id, line_number_as_pcl_comment())
            }

        self.points_by_metric_id[metric_id] = point_details

        return point_details

    def get_files(self):

        pass

    def get_loads(self):

        load_string = "Assembly/Analyses/FEA/Loads/Load"
        self.logger.info("Searching for {} ".format(load_string))
        load_nodes = self.cad_assm_root.findall(load_string)

        load_id_counter = 0
        load_value_id = '000{}'.format(line_number_as_pcl_comment())

        for l_node in load_nodes:
            load_id_counter += 1

            load_type = ''
            load_comments = ""
            metric_id = '000{}'.format(line_number_as_pcl_comment())
            geometry_id = '000{}'.format(line_number_as_pcl_comment())

            for child_node in l_node:
                if child_node.tag == 'Pressure':
                    load_type = 'PRESSURE'
                    load_value_id = self.get_load_value('Pressure', child_node)
                elif child_node.tag == 'Force':
                    load_type = 'FORCE'
                    load_value_id = self.get_load_value('Force', child_node)
                elif child_node.tag == 'ForceMoment':  # TODO
                    load_type = 'FORCEMOMENT'
                    load_value_id = self.get_load_value('ForceMoment', child_node)
                elif child_node.tag == 'Geometry':
                    self.logger.info("Searching for {} ".format("Features/Feature"))
                    feature_nodes = child_node.findall("Features/Feature")

                    if len(feature_nodes) > 1:
                        msg = "Red Alert: Multiple Features for one 'Load' node!"

                        load_comments += msg

                        for f in feature_nodes:
                            msg += "\n    _id: {}".format(f.attrib['_id'])

                        self.logger.error(msg)

                    feature_node = feature_nodes[0]
                    metric_id = feature_node.attrib['MetricID']
                    load_comments += "(MetricID: {})".format(metric_id)
                    associated_geometry = self.geometries_by_metric_id[metric_id]
                    geometry_id = associated_geometry['ID']

            xml_node_text = letree.tostring(l_node)

            load = {
                'Comments': load_comments,
                'XML_Text': xml_node_text,
                'ID': load_id_counter,
                'Type': load_type,
                'SubCase_ID': '1{}'.format(line_number_as_pcl_comment()),
                'Geometry_ID': geometry_id,
                'Load_Value_ID': load_value_id,
            }

            self.loads[metric_id] = load

    def get_load_value(self, type_name, load_value_node):

        load_value = {}

        load_value['XML_Text'] = letree.tostring(load_value_node)

        if type_name == 'ForceMoment':
            msg = "We have not handled 'ForceMoment' yet."
            self.logger.error(msg)
            self.failure(msg)

        elif type_name == 'Force':
            msg = "We have not handled 'Force' yet. (6/3/16)"
            self.logger.error(msg)
            self.failure(msg)

            # units = load_value_node.attrib['Units']
            # load_value['Comments'] = 'Units: {}'.format(units)
            #
            # value = load_value_node.get('Value', None)
            #
            # if value is not None:
            #     load_value['Value'] = value
            #
            # elif value is None:
            #     load_value['x_Value'] = str(load_value_node.get('x', None))
            #     load_value['y_Value'] = str(load_value_node.get('y', None))
            #     load_value['z_Value'] = str(load_value_node.get('z', None))

        elif type_name == 'Pressure':
            units = load_value_node.attrib['Units']
            load_value['Comments'] = 'Units: {}'.format(units)

            value = load_value_node.get('Value', None)

            if value is not None:
                load_value['Scalar_Value'] = value

            else:
                msg = "Pressure Value is 'None' ({})".format(load_value_node.attrib['_id'])
                self.failure()

            # if value is None:
            #     load_value['x_Value'] = str(load_value_node.get('x', None))
            #     load_value['y_Value'] = str(load_value_node.get('y', None))
            #     load_value['z_Value'] = str(load_value_node.get('z', None))

        if 'Scalar_Value' in load_value:
            load_value_id_counter = len(self.load_values['Scalar'])
            load_value_id_counter += 1
            load_value['ID'] = str(load_value_id_counter)

            self.load_values['Scalar'][load_value_id_counter] = load_value
        # else:
        #     load_value_id_counter = len(self.load_values['Vector'])
        #     load_value_id_counter += 1
        #     load_value['ID'] = str(load_value_id_counter)
        #
        #     self.load_values['Vector'][load_value_id_counter] = load_value

        return load_value_id_counter

    def create_pcl_text_block(self, section_info, block_indent='', copy_xml_text=True):

        header = section_info['SectionName']
        lines = section_info['Content']

        line_ending = '\n'

        indent = '    '

        block_string = block_indent + header + line_ending
        for line in lines:
            if '$XML_Text' in line:
                if not copy_xml_text:
                    continue

            line_string = block_indent + indent + line + line_ending
            block_string += line_string

        return block_string

    def create_pcl_input_file(self, copy_xml_text):

        line_ending = '\n'

        singles = {
            'Analysis': self.analysis,
            'Mesh_Parameters': self.mesh_parameters
        }

        hard_coded = [
            'SubCase',
            'Files'
        ]

        multiples = {
            'Point': self.points_by_metric_id,
            'Geometry': self.geometries_by_metric_id,
            'Surface': self.surfaces_by_metric_id,
            'Solid': self.solids,
            'Material': self.materials,
            'Load': self.loads,
            'Load_Value_Scalar': self.load_values['Scalar'],
            'Load_Value_Vector': self.load_values['Vector'],
            'Constraint': self.constraints_by_id,
            'Constraint_Specifier_Displacement': self.constraint_specifiers['Displacement'],
            'Constraint_Specifier_Pin': self.constraint_specifiers['Pin'],
            'Surface_Contents': self.surface_contents
        }

        specials = {
            'Material_Layup': self.layups
        }

        block_list = []
        pcl_input_string = ""

        # Singles
        for template_name, replacement_map in singles.iteritems():
            block_string = \
                self.create_pcl_text_block(self.pcl_template_json[template_name], copy_xml_text=copy_xml_text)
            template = string.Template(block_string)
            block_string = template.safe_substitute(replacement_map)

            block_list.append(block_string)
            pcl_input_string += block_string + line_ending

        # Hard-coded
        for template_name in hard_coded:
            block_string = \
                self.create_pcl_text_block(self.pcl_template_json[template_name], copy_xml_text=copy_xml_text)

            block_list.append(block_string)
            pcl_input_string += block_string + line_ending

        # Multiples
        for template_name, pcl_var in multiples.iteritems():
            for key, replacement_map in pcl_var.iteritems():
                block_string = \
                    self.create_pcl_text_block(self.pcl_template_json[template_name], copy_xml_text=copy_xml_text)
                template = string.Template(block_string)
                block_string = template.safe_substitute(replacement_map)

                # TODO: Remove lines with 'None'
                if template_name == 'Constraint_Specifier_Displacement':
                    block_string, deleted = remove_lines_with_none(block_string)
                    self.logger.info("Lines removed from {}: {}".format(template_name, deleted))

                block_list.append(block_string)
                pcl_input_string += block_string + line_ending

        # Specials
        for template_name, pcl_var in specials.iteritems():
            if template_name == 'Material_Layup':
                section_indent = '    '

                for cad_comp_id, layup_details in self.layups.iteritems():
                    pcl_input_string += template_name + line_ending
                    pcl_input_string += section_indent + "ID = {}".format(layup_details['ID']) + line_ending

                    for l_id in layup_details['LayerIDs']:
                        # 1st pass: get raw template string
                        block_string = \
                            self.create_pcl_text_block(
                                self.pcl_template_json['Layer'], section_indent, copy_xml_text=copy_xml_text)

                        # 2nd pass: replace placeholders with object instance data
                        template = string.Template(block_string)
                        replacement_map = self.layers[l_id]
                        block_string = template.safe_substitute(replacement_map)

                        block_list.append(block_string)
                        pcl_input_string += block_string + line_ending

            elif template_name == 'Surface_Contents':
                block_string = \
                    self.create_pcl_text_block(self.pcl_template_json[template_name], copy_xml_text=copy_xml_text)

                block_list.append(block_string)
                pcl_input_string += block_string + line_ending

        global_template = string.Template(pcl_input_string)
        pcl_input_string = global_template.safe_substitute(self.pcl_globals)

        with open(self.patran_input_file_name, 'w') as pcl_input_file:
            pcl_input_file.write(pcl_input_string)


def main():

    parser = argparse.ArgumentParser(description="reads in CADAssembly.xml, CADAssembly_metrics.xml, "
                                                 "and ComputedValues.xml and creates a .pcl script for Patran")
    parser.add_argument('-cadassembly',
                        default="CADAssembly.xml",
                        help="CADAssembly.xml filename")
    parser.add_argument('-cadassembly_metrics',
                        default="CADAssembly_metrics.xml",
                        help="CADAssembly_metrics.xml filename")
    parser.add_argument('-computedvalues',
                        default="ComputedValues.xml",
                        help="ComputedValues.xml filename")
    parser.add_argument('-copyxmltext',
                        default=False,
                        help="Copy xml text to PCL input file.")

    args = parser.parse_args()

    args.copyxmltext = True if args.copyxmltext == 'True' else False

    ppcl = PatranPCL(
        args.cadassembly,
        args.cadassembly_metrics,
        args.computedvalues)

    ppcl.create_pcl_input_file(args.copyxmltext)


if __name__ == '__main__':

    main()
