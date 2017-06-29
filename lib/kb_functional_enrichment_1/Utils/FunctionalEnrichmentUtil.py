import time
import json
import re
import fisher
from rpy2.robjects.packages import importr
from rpy2.robjects.vectors import FloatVector
import os
import uuid
import errno
import csv
import operator

from Workspace.WorkspaceClient import Workspace as Workspace
from DataFileUtil.DataFileUtilClient import DataFileUtil
from KBaseReport.KBaseReportClient import KBaseReport
from GenomeSearchUtil.GenomeSearchUtilClient import GenomeSearchUtil


def log(message, prefix_newline=False):
    """Logging function, provides a hook to suppress or redirect log messages."""
    print(('\n' if prefix_newline else '') + '{0:.2f}'.format(time.time()) + ': ' + str(message))


class FunctionalEnrichmentUtil:

    def _mkdir_p(self, path):
        """
        _mkdir_p: make directory for given path
        """
        if not path:
            return
        try:
            os.makedirs(path)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else:
                raise

    def _validate_run_fe1_params(self, params):
        """
        _validate_run_fe1_params:
                validates params passed to run_fe1 method
        """

        log('start validating run_fe1 params')

        # check for required parameters
        for p in ['genome_ref', 'workspace_name']:
            if p not in params:
                raise ValueError('"{}" parameter is required, but missing'.format(p))

    def _generate_report(self, enrichment_map, result_directory, workspace_name):

        """
        _generate_report: generate summary report
        """
        log('creating report')

        output_files = self._generate_output_file_list(result_directory,
                                                       enrichment_map)

        output_html_files = self._generate_html_report(result_directory,
                                                       enrichment_map)

        report_params = {
              'message': '',
              'workspace_name': workspace_name,
              'file_links': output_files,
              'html_links': output_html_files,
              'direct_html_link_index': 0,
              'html_window_height': 333,
              'report_object_name': 'kb_functional_enrichment_1_report_' + str(uuid.uuid4())}

        kbase_report_client = KBaseReport(self.callback_url)
        output = kbase_report_client.create_extended_report(report_params)

        report_output = {'report_name': output['name'], 'report_ref': output['ref']}

        return report_output

    def _generate_output_file_list(self, result_directory, enrichment_map):
        """
        _generate_output_file_list: zip result files and generate file_links for report
        """
        log('start packing result files')
        output_files = list()

        result_file = os.path.join(result_directory, 'functional_enrichment.csv')
        with open(result_file, 'wb') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(['go_id', 'go_term', 'raw_p_value', 'adjusted_p_value'])
            for key, value in enrichment_map.iteritems():
                writer.writerow([key, value['go_term'],
                                 value['raw_p_value'], value['adjusted_p_value']])

        output_files.append({'path': result_file,
                             'name': os.path.basename(result_file),
                             'label': os.path.basename(result_file),
                             'description': 'GO term functional enrichment'})

        return output_files

    def _generate_html_report(self, result_directory, enrichment_map):
        """
        _generate_html_report: generate html summary report
        """

        log('start generating html report')
        html_report = list()

        output_directory = os.path.join(self.scratch, str(uuid.uuid4()))
        self._mkdir_p(output_directory)
        result_file_path = os.path.join(output_directory, 'report.html')

        enrichment_table = ''
        data = csv.reader(open(os.path.join(result_directory, 'functional_enrichment.csv')),
                          delimiter=',')
        data.next()
        sortedlist = sorted(data, key=operator.itemgetter(3), reverse=True)
        for row in sortedlist[:20]:
            enrichment_table += '<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(*row)

        with open(result_file_path, 'w') as result_file:
            with open(os.path.join(os.path.dirname(__file__), 'report_template.html'),
                      'r') as report_template_file:
                report_template = report_template_file.read()
                report_template = report_template.replace('<tr>Enrichment_Table</tr>',
                                                          enrichment_table)
                result_file.write(report_template)

        report_shock_id = self.dfu.file_to_shock({'file_path': output_directory,
                                                  'pack': 'zip'})['shock_id']

        html_report.append({'shock_id': report_shock_id,
                            'name': os.path.basename(result_file_path),
                            'label': os.path.basename(result_file_path),
                            'description': 'HTML summary report for Functional Enrichment App'})
        return html_report

    def _get_go_maps_from_genome(self, genome_ref):
        """
        _search_genome: search genome data
        """
        log('start parsing GO terms from genome')
        feature_num = self.gsu.search({'ref': genome_ref})['num_found']

        genome_features = self.gsu.search({'ref': genome_ref,
                                           'limit': feature_num,
                                           'sort_by': [['feature_id', True]]})['features']

        feature_id_go_id_list_map = {}
        go_id_feature_id_list_map = {}
        go_id_go_term_map = {}
        feature_id_feature_info_map = {}
        for genome_feature in genome_features:
            feature_id = genome_feature.get('feature_id')
            feature_func = genome_feature.get('function')
            feature_type = genome_feature.get('feature_type')
            ontology_terms = genome_feature.get('ontology_terms')

            feature_id_feature_info_map.update({feature_id: {'function': feature_func,
                                                             'feature_type': feature_type}})

            go_id_list = []
            if ontology_terms:
                for ontology_id, ontology_term in ontology_terms.iteritems():
                    if re.match('[gG][oO]\:.*', ontology_id):
                        go_id_go_term_map.update({ontology_id: ontology_term})
                        go_id_list.append(ontology_id)

            if go_id_list:
                feature_id_go_id_list_map.update({feature_id: go_id_list})

                for go_id in go_id_list:
                    if go_id in go_id_feature_id_list_map:
                        feature_ids = go_id_feature_id_list_map.get(go_id)
                        feature_ids.append(feature_id)
                        go_id_feature_id_list_map.update({go_id: feature_ids})
                    else:
                        go_id_feature_id_list_map.update({go_id: [feature_id]})

        return (feature_id_go_id_list_map, go_id_feature_id_list_map,
                go_id_go_term_map, feature_id_feature_info_map)

    def _get_feature_set_ids(self):
        log('start generating feature set ids')
        feature_set_ids = ['AT1G01010', 'AT1G01030', 'AT1G01020', 'AT1G01050', 'AT1G01060']
        return feature_set_ids

    def __init__(self, config):
        self.ws_url = config['workspace-url']
        self.callback_url = config['SDK_CALLBACK_URL']
        self.token = config['KB_AUTH_TOKEN']
        self.shock_url = config['shock-url']
        self.scratch = config['scratch']
        self.dfu = DataFileUtil(self.callback_url)
        self.gsu = GenomeSearchUtil(self.callback_url)
        self.ws = Workspace(self.ws_url, token=self.token)

    def run_fe1(self, params):
        """
        run_fe1: Functional Enrichment One

        required params:
        genome_ref: Genome object reference
        workspace_name: the name of the workspace it gets saved to

        return:
        result_directory: folder path that holds all files generated by run_deseq2_app
        report_name: report name generated by KBaseReport
        report_ref: report reference generated by KBaseReport
        """
        log('--->\nrunning FunctionalEnrichmentUtil.run_fe1\n' +
            'params:\n{}'.format(json.dumps(params, indent=1)))

        self._validate_run_fe1_params(params)

        result_directory = os.path.join(self.scratch, str(uuid.uuid4()))
        self._mkdir_p(result_directory)

        genome_ref = params.get('genome_ref')
        (feature_id_go_id_list_map, go_id_feature_id_list_map,
         go_id_go_term_map, feature_id_feature_info_map) = self._get_go_maps_from_genome(genome_ref)

        feature_set_ids = self._get_feature_set_ids()
        feature_ids = feature_id_feature_info_map.keys()

        enrichment_map = {}
        go_raw_p_value = {}
        all_raw_p_value = []
        for go_id, go_term in go_id_go_term_map.iteritems():
            mapped_features = go_id_feature_id_list_map.get(go_id)
            # in feature_set matches go_id
            a = len(set(mapped_features).intersection(feature_set_ids))
            # in feature_set doesn't match go_id
            b = len(feature_set_ids) - a
            # not in feature_set matches go_id
            c = len(mapped_features) - a
            # not in feature_set doesn't match go_id
            d = len(feature_ids) - len(feature_set_ids) - c

            raw_p_value = fisher.pvalue(a, b, c, d).left_tail
            all_raw_p_value.append(raw_p_value)
            go_raw_p_value.update({go_id: raw_p_value})

        stats = importr('stats')
        adjusted_p_values = stats.p_adjust(FloatVector(all_raw_p_value), method='fdr')

        for go_id, raw_p_value in go_raw_p_value.iteritems():
            pos = all_raw_p_value.index(raw_p_value)
            adjusted_p_value = adjusted_p_values[pos]
            enrichment_map.update({go_id: {'raw_p_value': raw_p_value,
                                           'adjusted_p_value': adjusted_p_value,
                                           'go_term': go_id_go_term_map.get(go_id)}})

        returnVal = {'result_directory': result_directory}
        report_output = self._generate_report(enrichment_map,
                                              result_directory,
                                              params.get('workspace_name'))

        returnVal.update(report_output)

        return returnVal
