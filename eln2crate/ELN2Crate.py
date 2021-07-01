import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from datetime import datetime
from pathlib import Path
from urllib import parse

from bs4 import BeautifulSoup
from bs4 import element as BeautifulSoup_element
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import FOAF, OWL, RDF, RDFS, XSD
from pathvalidate import sanitize_filename

from .Activities import activities
from .IDGenerator import IDGenerator
from .Manufacturers import manufacturers
from .MIMETypes import mime_types
from .Persons import persons, institutions
from .Templates import templates

class ProtocolElementUnknown(Exception):
    pass

class ELN2Crate:
    def __init__(self, logger, namespace_url, elabftw_url, elabftw_manager, exp_id, pseudonymize_persons):
        self.log = logger
        self.elabftw_url = elabftw_url
        self.elabftw_manager = elabftw_manager
        self.tempfolder = tempfile.mkdtemp()
        self.pseudonymize_persons = pseudonymize_persons
        self._get_experiment_information(exp_id)
        self.general_namespace = Namespace(namespace_url + '/')
        self.protocol_namespace = Namespace('%s/%s/' % (namespace_url, self.exp['id']))
        self.id_generator = IDGenerator(self.general_namespace, self.protocol_namespace)
        self.graph = Graph()
        self.graph_context = [
            'https://w3id.org/ro/crate/1.1/context',
            {
                #'@base': self.protocol_namespace,
                #'@vocab': 'https://schema.org/',
                'foaf': FOAF,
                'xsd': XSD,
                'rdfs': 'http://www.w3.org/2000/01/rdf-schema#', # NOTE: using RDFS here throws some error
                'owl': OWL,
                'wd': 'https://www.wikidata.org/entity/',
                'prov': 'http://www.w3.org/ns/prov#'
            }
        ]

    @staticmethod
    def create_folder_if_not_exists(folder):
        pfolder = Path(folder)
        pfolder.mkdir(exist_ok=True)

    def _update_protocol_links_to_local(self):
        for link in self.exp['soup'].find_all('a'):
            if not 'database.php' in link.get('href'):
                continue

            item_id = link.get('href').split('&')[1].replace('id=', '')
            for item in self.items:
                if item['id'] == item_id:
                    link['href'] = 'Database/%s.html' % (
                        sanitize_filename('%s - %s' % (item['category'], item['title']))
                    )
                    link['target'] = '_blank'
                    # also update the item so that we can re-use the link for
                    # matching the item later:
                    item['ro-crate_link'] = link['href']

    def write_files(self):
        self._write_experiment_body()
        self._write_database_items()
        self._write_attachments()

    def _write_experiment_body(self):
        filename = sanitize_filename(self.exp['title']) + '.html'
        protocol_path = os.path.join(self.tempfolder, 'Protocol')
        ELN2Crate.create_folder_if_not_exists(protocol_path)

        self._update_protocol_links_to_local()
        with open(os.path.join(protocol_path, filename), 'w') as file:
            file.write(str(self.exp['soup']))

    def _write_database_items(self):
        database_path = os.path.join(self.tempfolder, 'Protocol/Database')
        ELN2Crate.create_folder_if_not_exists(database_path)

        for item in self.items:
            filename = sanitize_filename('%s - %s' % (item['category'], item['title'])) + '.html'
            with open(os.path.join(database_path, filename), 'w') as file:
                file.write(item['body'])

    def _write_attachments(self):
        attachment_path = os.path.join(self.tempfolder, 'Data')
        ELN2Crate.create_folder_if_not_exists(attachment_path)

        for upload in self.exp.get('uploads'):
            complete_name = os.path.join(attachment_path, upload['real_name'])
            with open(complete_name, 'wb') as datafile:
                datafile.write(self.elabftw_manager.get_upload(upload['id']))

    def _get_experiment_information(self, exp_id):
        self.exp = self.elabftw_manager.get_experiment(exp_id)
        # Pseudonymize persons
        for i, name in enumerate(self.pseudonymize_persons):
            self.exp['body'] = self.exp['body'].replace(name, 'Anonymous Person%d' % (i+1))
        self.exp['soup'] = BeautifulSoup(self.exp['body'], 'html.parser')
        self._get_database_items()

    def _get_database_items(self):
        self.items = []
        # Note: we assume that all items linked in the text appear also in the links
        # at the end of the protocol in order to ensure this, run `updating_links.ipynb`
        for item in self.exp.get('links'):
            self.items.append(self.elabftw_manager.get_item(item['itemid']))

    def _call_siegfried(self):
        folder_path = os.path.abspath(self.tempfolder)
        result = subprocess.run(' '.join([
            '/usr/bin/docker',
            'run',
            '--rm',
            '-v',
            '%s:%s' % (folder_path, folder_path),
            '--user',
            '$(id -u)',
            'sfbelaine/common:siegfried_latest',
            'sf',
            '-sourceinline',
            '-json',
            '-hash',
            'sha512',
            '-utc',
            '-z',
            folder_path
        ]), capture_output=True, shell=True, check=True)

        jsonfile_name = os.path.join(self.tempfolder, 'siegfried_output.json')
        with open(jsonfile_name, 'wb') as jsonfile:
            jsonfile.write(result.stdout)

        return jsonfile_name

    def create_model(self):
        self.sf_output = self._call_siegfried()
        self._model_items()
        self._model_protocol()
        self._model_rocrate_base()
        self._model_attachments()

        return self.graph

    def _model_attachments(self):
        # loop over all files in the tempfolder to include HTML export and attachments
        for filename in glob.glob(os.path.join(self.tempfolder, '**/*'), recursive=True):
            if os.path.isdir(filename):
                # we don't want to model directories
                continue

            filename_clean = filename.replace(self.tempfolder + '/', '') # remove temporary folder
            filename_dir, filename_base = os.path.split(filename_clean)
            _, filename_ending = os.path.splitext(filename_base)
            graph_id = self.id_generator.getFile(filename_clean)
            self.graph.add((graph_id, FOAF.name, Literal(filename_clean, lang='en')))
            self.graph.add((graph_id, RDF.type, URIRef('File')))
            self.graph.add((
                graph_id,
                URIRef('encodingFormat'),
                Literal(mime_types.get(filename_ending))
            ))

            self.graph.add((self.graph_dir, URIRef('hasPart'), graph_id))

            # siegfried output should be added, but don't cover further reasoning
            if filename_base == 'siegfried_output.json':
                # add siegfried meta data
                with open(self.sf_output) as data_file:
                    data = json.load(data_file)
                    # 2021-04-12T09:21:53Z
                    lastchange = datetime.strptime(data['scandate'], '%Y-%m-%dT%H:%M:%SZ')
                    self.graph.add((
                        graph_id,
                        URIRef('https://schema.org/dateModified'),
                        Literal(lastchange, datatype=XSD.dateTime)
                    ))
                    # the following information will be skipped for now
                    #self.graph.add((graph_id, URIRef('siegfried'), Literal(data['siegfried'])))
                    #self.graph.add((graph_id, URIRef('signature'), Literal(data['signature'])))
                    #self.graph.add((graph_id, URIRef('created'), Literal(data['created'])))
                    #self.graph.add((
                    #    graph_id,
                    #    URIRef('identifiers'),
                    #    Literal(json.dumps(data['identifiers']))
                    # ))
                continue

            # check if additional information are inside elabFTW
            # Data folder contains uploads only, so we can rely on the file name
            if os.path.basename(filename_dir) == 'Data':
                for upload in self.exp.get('uploads'):
                    if upload['real_name'] == filename_base:
                        lastchange = datetime.strptime(upload['datetime'], '%Y-%m-%d %H:%M:%S')
                        self.graph.add((
                            graph_id,
                            URIRef('https://schema.org/dateModified'),
                            Literal(lastchange, datatype=XSD.dateTime)
                        ))
                        # Disable this as it allows anybody to download the file
                        # download_url = '%s/app/download.php?f=%s&name=%s&forceDownload' % (
                        #     self.elabftw_url,
                        #     upload['long_name'],
                        #     upload['real_name']
                        # )
                        # self.graph.add((
                        #     graph_id,
                        #     URIRef('url'),
                        #     Literal(download_url, datatype=XSD.anyUri)
                        # ))
                        break

            ###################################################################
            # NOTE: We don't add modification date and URLs for Protocol and Database Items
            #  as these are already present in the nodes representing the items
            #
            # elif os.path.basename(filename_dir) == 'Protocol':
            #     # the expriment export is the only file inside this folder
            #     lastchange = datetime.strptime(self.exp['lastchange'], '%Y-%m-%d %H:%M:%S')
            #     self.graph.add((
            #         graph_id,
            #         URIRef('https://schema.org/dateModified'),
            #         Literal(lastchange, datatype=XSD.dateTime)
            #     ))
            #     experiment_url = '%s/experiments.php?mode=view&id=%s' % (
            #         self.elabftw_url,
            #         self.exp['id']
            #     )
            #     self.graph.add((
            #         graph_id,
            #         URIRef('url'),
            #         Literal(experiment_url, datatype=XSD.anyUri)
            #     ))
            # elif os.path.basename(filename_dir) == 'Database':
            #     for item in self.items:
            #         name = '%s.html' % (
            #             sanitize_filename('%s - %s' % (item['category'], item['title']))
            #         )
            #         if name == filename_base:
            #             lastchange = datetime.strptime(item['lastchange'], '%Y-%m-%d %H:%M:%S')
            #             self.graph.add((
            #                 graph_id,
            #                 URIRef('https://schema.org/dateModified'),
            #                 Literal(lastchange, datatype=XSD.dateTime)
            #             ))
            #             database_url = '%s/database.php?mode=view&id=%s' % (
            #                 self.elabftw_url,
            #                 item['id']
            #             )
            #             self.graph.add((
            #                 graph_id,
            #                 URIRef('url'),
            #                 Literal(database_url, datatype=XSD.anyUri)
            #             ))
            #             break
            ###################################################################

            # check if we find corresponding match from siegefried outout
            with open(self.sf_output) as data_file:
                data = json.load(data_file)

                for metadata in data['files']:
                    if filename == metadata['filename'].replace('/tmp/siegfried-files/', ''):
                        self.graph.add((
                            graph_id,
                            URIRef('contentSize'),
                            Literal(metadata['filesize'])
                        ))
                        self.graph.add((graph_id, URIRef('sha512'), Literal(metadata['sha512'])))
                        # Skip the following information from siegfried for now
                        # self.graph.add((
                        #     graph_id,
                        #     URIRef('matches'),
                        #     Literal(json.dumps(metadata['matches']))
                        # ))
                        # self.graph.add((graph_id, URIRef('errors'), Literal(metadata['errors'])))
                        break


    def _model_items(self):
        # TODO: add the author of the item?
        for item in self.items:
            graph_item = self.id_generator.getDBItem(item)
            self.graph.add((graph_item, FOAF.name, Literal(item['title'], lang='en')))
            self.graph.add((graph_item, RDF.type, URIRef('IndividualProduct')))
            # TODO: the following might be integrated in order to reference the internal category
            # self.graph.add((graph_item, URIRef('category'), Literal(item['category'], lang='en')))

            # Example: '2021-01-21 16:00:20'
            lastchange = datetime.strptime(item['lastchange'], '%Y-%m-%d %H:%M:%S')
            self.graph.add((
                graph_item,
                URIRef('https://schema.org/dateModified'),
                Literal(lastchange, datatype=XSD.dateTime)
            ))
            # disable the database url for now
            # database_url = '%s/database.php?mode=view&id=%s' % (
            #     self.elabftw_url,
            #     item['id']
            # )
            # self.graph.add((
            #     graph_item,
            #     URIRef('url'),
            #     Literal(database_url, datatype=XSD.anyUri)
            # ))
            self.graph.add((
                graph_item,
                URIRef('hasFile'),
                self.id_generator.getFile(os.path.join('Protocol/', item['ro-crate_link']))
            ))

            # now, try to find item types and wikidata items
            item['soup'] = BeautifulSoup(item['body'], 'html.parser')
            table = item['soup'].find('table')
            assigned = False
            if table:
                for row in table.find_all('tr'):
                    content = row.contents[1].text.strip().lower()
                    if content == 'ontology-item':
                        self.graph.add((
                            graph_item,
                            OWL.sameAs,
                            URIRef(row.contents[3].text.strip())
                        ))
                        assigned = True
                        continue

                    if content == 'wikidata-item':
                        self.graph.add((
                            graph_item,
                            OWL.sameAs,
                            URIRef(row.contents[3].text.strip())
                        ))
                        continue


                    if content in ['manufacturer', 'supplier', 'developer']:
                        manufacturer_id = self._model_manufacturer(\
                            row.contents[3].text.strip().lower())
                        self.graph.add((
                            graph_item,
                            URIRef('http://purl.obolibrary.org/obo/OBI_0000647'), # has supplier
                            manufacturer_id
                        ))
                        continue

                    if content in [prefix + '-id' for prefix in \
                        ['manufacturer', 'supplier', 'developer']]:
                        self.graph.add((
                            graph_item,
                            URIRef('has_supplier_id'), # FIXME: define custom relation
                            Literal(row.contents[3].text.strip())
                        ))
                        continue

                    self.log.debug('Found content of DB item "%s" that has not been handled: "%s"'\
                        % (item['title'], content))


            if not assigned:
                self.log.error(
                    '''Database item does not have a table inside the body or no
                    row with "ontology-item" was found: id=%s, name=%s''' % (
                        item['id'],
                        item['title']
                    )
                )


    def _model_rocrate_base(self):
        graph_base = URIRef('ro-crate-metadata.json')
        self.graph_dir = self.id_generator.getDataset()
        self.graph.add((graph_base, RDF.type, URIRef('CreativeWork')))
        self.graph.add((
            graph_base,
            URIRef('conformsTo'),
            URIRef('https://w3id.org/ro/crate/1.1')
        ))
        self.graph.add((graph_base, URIRef('about'), self.graph_dir))

        self.graph.add((self.graph_dir, RDF.type, URIRef('Dataset')))
        self.graph.add((self.graph_dir, URIRef('creator'), self.researcher_id))
        for tag in self.exp['tags'].split('|'):
            self.graph.add((self.graph_dir, URIRef('keywords'), Literal(tag, lang='en')))
        self.graph.add((
            self.graph_dir,
            URIRef('name'),
            Literal(self.exp['title'], lang='en')
        ))
        lastchange = datetime.strptime(self.exp['lastchange'], '%Y-%m-%d %H:%M:%S')
        self.graph.add((
            self.graph_dir,
            URIRef('datePublished'),
            Literal(lastchange, datatype=XSD.dateTime)
        ))

        # FIXME: adjust to corresponding license
        license_id = URIRef('https://creativecommons.org/licenses/by/4.0/')
        self.graph.add((self.graph_dir, URIRef('license'), license_id))
        self.graph.add((license_id, RDF.type, URIRef('CreativeWork')))
        self.graph.add((
            license_id,
            URIRef('name'),
            Literal('Attribution 4.0 International (CC BY 4.0)', lang='en')
        ))
        self.graph.add((license_id, URIRef('identifier'), license_id))
        self.graph.add((
            license_id,
            URIRef('description'),
            Literal('This work is licensed under a Creative Commons Attribution 4.0 International License.', lang='en')
        ))

    def _model_manufacturer(self, manufacturer_name):
        for manufacturer_key in manufacturers.keys():
            if manufacturer_key in manufacturer_name:
                manufacturer_info = manufacturers[manufacturer_key]
                manufacturer_id = self.id_generator.getManufacturer(manufacturer_key, manufacturer_info)

                self.graph.add((
                    manufacturer_id,
                    FOAF.name,
                    Literal(manufacturer_info['name'])
                ))

                self.graph.add((
                    manufacturer_id,
                    RDF.type,
                    URIRef('http://purl.obolibrary.org/obo/OBI_0000835') # manufacturer
                ))

                return manufacturer_id

        self.log.error('Could not find manufacturer name: "%s"' % (manufacturer_name))
        sys.exit(1)

    def _add_parameter_nodes(self, step_id, value_specification, label, value, unit):
        node_id = BNode()
        self.graph.add((node_id, RDF.type, value_specification))
        self.graph.add((node_id, RDFS.label, label))
        self.graph.add((node_id, URIRef('prov:value'), value))
        self.graph.add((
            node_id,
            URIRef('http://purl.obolibrary.org/obo/IAO_0000039'), # has measurement unit label
            unit
        ))
        self.graph.add((
            step_id,
            URIRef('http://purl.obolibrary.org/obo/OBI_0001938'), # has value specification
            node_id
        ))


    def _model_parameters(self, step_id, description):
        # TEMPERATURE
        for temperature_search in re.finditer(r'[+-]?[\.\d]+\s*°\s*C', description):
            temperature = temperature_search.group()

            if re.search(r'°\s*C', temperature):
                self._add_parameter_nodes(
                    step_id,
                    URIRef('http://purl.obolibrary.org/obo/OBI_0002138'),
                    Literal(temperature),
                    Literal(
                        re.match(r'[+-]?[\.\d]+', temperature.strip()).group(),
                        datatype=XSD.decimal
                    ),
                    URIRef('http://purl.obolibrary.org/obo/UO_0000027') # degree Celsius
                )
            else:
                self.log.error('Temperature uses unknown unit: '+ temperature)
                sys.exit(1)

        # FREQUENCY
        for frequency_search in re.finditer(r'[+-]?[\.\d]+\s*Hz', description):
            frequency = frequency_search.group()

            if re.search(r'Hz', frequency):
                self._add_parameter_nodes(
                    step_id,
                    URIRef('http://purl.obolibrary.org/obo/OBI_0001931'),
                    Literal(frequency),
                    Literal(
                        re.match(r'[+-]?[\.\d]+', frequency.strip()).group(),
                        datatype=XSD.decimal
                    ),
                    URIRef('http://purl.obolibrary.org/obo/UO_0000106') # degree Celsius
                )
            else:
                self.log.error('frequency uses unknown unit: '+ frequency)
                sys.exit(1)

        # DURATION
        for duration_search in re.finditer(r'[+-]?[\.\d]+\s*(min|ms)', description):
            duration = duration_search.group()

            duration_unit = None
            if re.search(r'min', duration):
                duration_unit = URIRef('http://purl.obolibrary.org/obo/UO_0000031') # minute
            elif re.search(r'ms', duration):
                duration_unit = URIRef('http://purl.obolibrary.org/obo/UO_0000028') # millisecond
            else:
                self.log.error('Duration uses unknown unit: '+ duration)
                sys.exit(1)

            self._add_parameter_nodes(
                step_id,
                URIRef('http://purl.obolibrary.org/obo/OBI_0001931'),
                Literal(duration),
                Literal(re.match(r'[+-]?[\.\d]+', duration.strip()).group(), \
                    datatype=XSD.nonNegativeInteger),
                duration_unit
            )

        # VOLTAGE
        for voltage_search in re.finditer(r'[+-]?[\.\d]+\s*V', description):
            voltage = voltage_search.group()

            if re.search(r'V', voltage):
                self._add_parameter_nodes(
                    step_id,
                    URIRef('http://purl.obolibrary.org/obo/OBI_0001931'),
                    Literal(voltage),
                    Literal(re.match(r'[+-]?[\.\d]+', voltage.strip()).group(), \
                        datatype=XSD.nonNegativeInteger),
                    URIRef('http://purl.obolibrary.org/obo/UO_0000218') # V
                )
            else:
                self.log.error('Voltage uses unknown unit: '+ voltage)
                sys.exit(1)


    def _model_researcher(self, researcher_name):
        if persons.get(researcher_name):
            researcher = persons.get(researcher_name)
            organization = institutions.get(researcher['affiliation'])
            organization_id = self.id_generator.getInstitution(
                researcher['affiliation'],
                organization
            )
            researcher_id = self.id_generator.getResearcher(researcher_name, researcher)

            if (researcher_id, RDF.type, URIRef('prov:Person')) in self.graph:
                return researcher_id, organization_id

            if (organization_id, RDF.type, URIRef('prov:Organization')) not in self.graph:
                self.graph.add((organization_id, RDF.type, URIRef('prov:Organization')))
                self.graph.add((
                    organization_id,
                    URIRef('foaf:name'),
                    Literal(organization['name'], lang='en')
                ))

            self.graph.add((researcher_id, RDF.type, URIRef('prov:Person')))
            self.graph.add((
                researcher_id,
                URIRef('foaf:name'),
                Literal("%s %s" % (researcher['givenName'], researcher['familyName']), \
                    datatype=XSD.string)
            ))
            self.graph.add((
                researcher_id,
                URIRef('foaf:givenName'),
                Literal(researcher['givenName'], datatype=XSD.string)
            ))
            self.graph.add((
                researcher_id,
                URIRef('foaf:familyName'),
                Literal(researcher['familyName'], datatype=XSD.string)
            ))
            # self.graph.add((researcher_id, URIRef('identifier'), researcher_id))
            if researcher.get('email'):
                self.graph.add((
                    researcher_id,
                    URIRef('email'),
                    Literal(researcher['email'])
                ))
            self.graph.add((researcher_id, URIRef('affiliation'), organization_id))
        else:
            self.log.error('Could not find researcher name: "%s"' % (researcher_name))
            sys.exit(1)

        return researcher_id, organization_id

    def _model_general_element(self, element):
        count_links = 0
        current_items = []
        tmp_items = []

        # NavigableStrings do not contain links, we can stop here
        if isinstance(element, BeautifulSoup_element.NavigableString):
            return []

        for link in element.find_all('a'):
            if link['href'].startswith('Database'):
                for item in self.items:
                    if item['ro-crate_link'] == link['href']:
                        count_links += 1
                        tmp_items.append(item)
                        current_items.append(self.id_generator.getDBItem(item))
                        break

        # check for LOT number, passage number and attributions
        # NOTE: we assume that in a single list item there is maximum one of each:
        # * LOT number
        # * passage number
        # * attribution
        lot_search = re.search(r'LOT \w+', element.text)
        passage_search = re.search(r'Passage \d+', element.text)
        attributed_search = re.search(r'\(Attributed to .+\)', element.text)

        if attributed_search:
            # first of all, add researcher
            researcher_name = \
                attributed_search.group()[:-1].replace('(Attributed to', '').strip().lower()
            researcher_id, _ = self._model_researcher(researcher_name)

        # we found at least one link to a database item
        if count_links == 1:
            db_id = current_items[0]
            if lot_search:
                lot_number = lot_search.group().replace('LOT ', '')
                if passage_search:
                    medium_id = self.id_generator.getDBLotPassageInstance( \
                        tmp_items[0], lot_number, passage_search.group().replace('Passage ', ''))
                else:
                    medium_id = self.id_generator.getDBLotInstance(tmp_items[0], lot_number)

                if (medium_id, None, None) not in self.graph:
                    # copy medium information
                    for _, p, o in self.graph.triples((db_id, None, None)):
                        self.graph.add((medium_id, p, o))
                    # now add LOT-specific infos
                    self.graph.add((
                        medium_id,
                        URIRef('has_lot_number'), # FIXME: define custom relation
                        Literal(lot_search.group(), lang='en')
                    ))
                    self.graph.add((
                        medium_id,
                        URIRef('is_instance_of'), # FIXME: define custom relation
                        db_id
                    ))
                    if passage_search:
                        self.graph.add((
                            medium_id,
                            URIRef('has_passage_number'), # FIXME: define custom relation
                            Literal(passage_search.group(), lang='en')
                        ))

                # NOTE: as we use a lot/passage number, replace item with the specific id
                current_items = [medium_id]

        if count_links > 1:
            # check if we have the medium description which actually is a mixture
            if '+' in element.text.lower():
                # now, let's parse concentrations,
                # NOTE: we assume there are only percentage characters in the
                # specification of the serum so that they exist exactly
                # <count_links> times and in the same order as in tmp_items
                concentration_search = re.findall(r'[\.\d]+\s*%', element.text)
                if len(concentration_search) != count_links:
                    self.log.error('Found more percentages than database items in mixture "%s"' % \
                        (element.text))
                    sys.exit(1)

                # create plan specification
                # check if it does not exists
                medium_name = ''
                medium_foaf_name = ''
                for idx, item in enumerate(tmp_items):
                    medium_name += '_' if idx > 0 else ''
                    medium_name += '%s-%s' % (
                        concentration_search[idx].replace('%', '').strip(),
                        item['id']
                    )
                    medium_foaf_name += ' + ' if idx > 0 else ''
                    medium_foaf_name += '%s %s' % (
                        concentration_search[idx],
                        item['title']
                    )
                # find new medium number that is not already in the graph unless we find
                medium_number = 1
                found_existing = False
                while True:
                    medium_id = self.id_generator.getMixture(medium_name, medium_number)
                    medium_creating_id = self.id_generator.getMixtureCreating(medium_name,\
                        medium_number)
                    if (medium_id, RDF.type, URIRef('http://purl.obolibrary.org/obo/OBI_0302729')) not in self.graph:
                        break
                    # if the medium is attributed to this researcher
                    # OR
                    # if the medium is not attributed at all and there is no researcher
                    # THEN: use the current one
                    if (attributed_search and \
                        (medium_id, URIRef('prov:wasAttributedTo'), researcher_id) in self.graph) or \
                        (not attributed_search and \
                            (medium_id, URIRef('prov:wasAttributedTo'), None) not in self.graph):
                        # stop here, as we can re-use the medium_id
                        found_existing = True
                        break

                    medium_number += 1

                if not found_existing:
                    # check if the plan is existing
                    plan_number = 1
                    found_existing_plan = False
                    while True:
                        medium_plan_id = self.id_generator.getMixturePlan(medium_name, plan_number)
                        if (medium_plan_id, RDF.type, URIRef('http://purl.obolibrary.org/obo/OBI_0000686')) not in self.graph:
                            break

                        if (medium_plan_id, RDFS.label, Literal(medium_foaf_name, lang='en')) in self.graph:
                            found_existing_plan = True
                            break

                        plan_number += 1

                    if not found_existing_plan:
                        self.graph.add((
                            medium_plan_id,
                            RDF.type,
                            URIRef('http://purl.obolibrary.org/obo/OBI_0000686') # material combination objective
                        ))
                        self.graph.add((
                            medium_plan_id,
                            RDFS.label,
                            Literal(medium_foaf_name, lang='en')
                        ))
                    # create mixture activity
                    self.graph.add((
                        medium_creating_id,
                        RDF.type,
                        URIRef('http://purl.obolibrary.org/obo/OBI_0000685')
                    ))
                    self.graph.add((
                        medium_creating_id,
                        URIRef('http://purl.obolibrary.org/obo/OBI_0000417'), # achieves_planned_objective
                        medium_plan_id
                    ))
                    self.graph.add((
                        medium_creating_id,
                        URIRef('http://purl.obolibrary.org/obo/OBI_0000299'), # has_specified_output
                        medium_id
                    ))

                    for item in current_items:
                        self.graph.add((
                            medium_creating_id,
                            URIRef('http://purl.obolibrary.org/obo/OBI_0000293'), # has_specified_input #TODO: Alternative: prov:used?
                            item
                        ))

                    # create mixture
                    self.graph.add((
                        medium_id,
                        RDF.type,
                        URIRef('http://purl.obolibrary.org/obo/OBI_0302729')
                    ))
                    self.graph.add((
                        medium_id,
                        FOAF.name,
                        Literal(medium_foaf_name)
                    ))

                # NOTE: as we use the mixture instead, replace all items with the mixture id
                current_items = [medium_id]

                if attributed_search:
                    self.graph.add((medium_id, URIRef('prov:wasAttributedTo'), researcher_id))

        return current_items

    def _model_general_part(self, element_part):
        used_items = []

        if element_part == '\n':
            return []

        if element_part.name == 'ul' or element_part.name == 'ol':
            for element in element_part.find_all('li'):
                used_items += self._model_general_element(element)
        else:
            used_items += self._model_general_element(element_part)

        return used_items


    def _model_protocol(self):
        approach_count = 0
        protocol_sections = []
        for headline in self.exp['soup'].find_all('h1'):
            part_text = headline.text.lower()

            if part_text == 'general information':
                table = headline.find_next_sibling('table')
                for row in table.find_all('tr'):
                    col_name = row.contents[1].text.lower().strip()
                    if col_name == 'researcher':
                        researcher_name = row.contents[3].text.strip().lower()
                        self.researcher_id, self.organization_id = \
                            self._model_researcher(researcher_name)
                    elif col_name == 'objective':
                        self.objective_id = self.id_generator.getObjective()
                        self.graph.add((
                            self.objective_id,
                            RDF.type,
                            URIRef('http://purl.obolibrary.org/obo/IAO_0000005') # objective specification
                        ))
                        self.graph.add((
                            self.objective_id,
                            RDFS.label,
                            Literal(row.contents[3].text.strip(), lang='en')
                        ))
                        self.graph.add((
                            self.id_generator.getProtocol(),
                            URIRef('http://purl.obolibrary.org/obo/OBI_0000417'),
                            self.objective_id
                        ))

            elif part_text == 'protocol':
                for stage in headline.find_next_siblings('h2'):
                    # first of all, check for a listing at the beginning
                    used_items = []
                    for sibling in stage.next_siblings:
                        if sibling.name == 'ul':
                            used_items = self._model_general_part(sibling)

                        if sibling.name == 'h2':
                            break

                    # next, check for the main part: a table
                    # note, we assume there is exactly one table for each stage
                    table = stage.find_next_sibling('table')
                    stage_text = stage.text.lower().strip()
                    if stage_text == 'preparation':
                        self._model_stage('preparation', 'Preparation', table, used_items, \
                            'ca-imaging_preparation')
                        protocol_sections.append('preparation')
                        continue

                    if stage_text == 'cell culture':
                        self._model_stage('cell_culture', 'Cell culture', table, used_items, \
                                'ca-imaging_cell_culture')
                        protocol_sections.append('cell_culture')
                        continue

                    if stage_text == 'fluo-3 staining':
                        self._model_stage('fluo-3_staining', 'Fluo-3 Staining', table, used_items, \
                                'ca-imaging_fluo-3_staining')
                        protocol_sections.append('fluo-3_staining')
                        continue

                    if 'approach' in stage_text:
                        approach_count += 1
                        if 'without stimulation' in stage_text:
                            stage_name = 'approach_%i_without_stimulation' % (approach_count)
                            self._model_stage(stage_name, stage.text.strip(), table, used_items, \
                                'ca-imaging_approach_without_stimulation')
                            protocol_sections.append(stage_name)
                            continue

                        if 'stimulation' in stage_text:
                            stage_name = 'approach_%i_with_stimulation' % (approach_count)
                            self._model_stage(stage_name, stage.text.strip(), table, used_items, \
                                'ca-imaging_approach_with_stimulation')
                            protocol_sections.append(stage_name)
                            continue

                    raise ProtocolElementUnknown(stage.text)

                # now, add the protocol sections as parts to the main protocol node
                protocol_id = self.id_generator.getProtocol()
                self.graph.add((protocol_id, RDF.type, URIRef('Action')))
                self.graph.add((protocol_id, RDF.type, URIRef('bfo:process')))
                self.graph.add((protocol_id, RDF.type, URIRef('prov:Activity')))
                self.graph.add((
                    protocol_id,
                    URIRef('foaf:name'),
                    Literal(self.exp['title'], lang='en')
                ))
                self.graph.add((
                    protocol_id,
                    URIRef('experiment_success'),
                    Literal(True if self.exp['category'] == 'Success' else False, \
                        datatype=XSD.boolean)
                ))
                # TODO: add RDF.type
                self.graph.add((
                    protocol_id,
                    URIRef('hasFile'),
                    self.id_generator.getFile(\
                        os.path.join('Protocol/', sanitize_filename(self.exp['title']) + '.html'))
                ))
                for idx, section in enumerate(protocol_sections):
                    self.graph.add((
                        protocol_id,
                        URIRef('hasPart'),
                        self.id_generator.getProtocolSection(section)
                    ))
                    if idx > 0:
                        self.graph.add((
                            self.id_generator.getProtocolSection(protocol_sections[idx]),
                            URIRef('prov:wasInformedBy'),
                            self.id_generator.getProtocolSection(protocol_sections[idx-1])
                        ))

                # now, let's model the template:
                for tag in self.exp['tags'].split('|'):
                    tag_lower = tag.lower()
                    if templates.get(tag_lower):
                        template_id = self.id_generator.getTemplate(tag_lower)
                        self.graph.add((
                            template_id,
                            RDF.type,
                            URIRef('prov:Plan')
                        ))
                        self.graph.add((
                            template_id,
                            FOAF.name,
                            Literal(tag)
                        ))
                        bassociation_id = BNode()
                        self.graph.add((
                            protocol_id,
                            URIRef('prov:qualifiedAssociation'),
                            bassociation_id
                        ))
                        self.graph.add((
                            bassociation_id,
                            RDF.type,
                            URIRef('prov:Association')
                        ))
                        self.graph.add((
                            bassociation_id,
                            URIRef('prov:hadPlan'),
                            template_id
                        ))
                        self.graph.add((
                            bassociation_id,
                            URIRef('prov:agent'),
                            self.researcher_id
                        ))
                        break

    def _model_stage(self, stage_name, title, soup_table, used_items, template_name):
        stage_id = self.id_generator.getProtocolSection(stage_name)

        self.graph.add((
            stage_id,
            URIRef('description'),
            Literal(title, lang='en')
        ))
        # TODO: add RDF.type for combination

        template_id = self.id_generator.getSectionTemplate(template_name)
        self.graph.add((
            template_id,
            RDF.type,
            URIRef('prov:Plan')
        ))
        self.graph.add((
            template_id,
            FOAF.name,
            Literal(template_name)
        ))
        bassociation_id = BNode()
        self.graph.add((
            stage_id,
            URIRef('prov:qualifiedAssociation'),
            bassociation_id
        ))
        self.graph.add((
            bassociation_id,
            RDF.type,
            URIRef('prov:Association')
        ))
        self.graph.add((
            bassociation_id,
            URIRef('prov:hadPlan'),
            template_id
        ))
        self.graph.add((
            bassociation_id,
            URIRef('prov:agent'),
            self.researcher_id
        ))

        self._add_used_items(stage_id, used_items)

        self._model_general_steps(
            soup_table,
            stage_name
        )

    def _add_used_items(self, node_id, used_items):
        for item in used_items:
            self.graph.add((node_id, URIRef('prov:used'), item))


    def _model_general_steps(self, soup_table, id_prefix):
        for idx, row in enumerate(soup_table.find_all('tr')):
            if idx == 0:
                continue

            step_id = self.id_generator.getProtocolStep(id_prefix, idx)
            section_id = self.id_generator.getProtocolSection(id_prefix)
            description_text = row.contents[1].text.strip()
            description_wo_links = copy.copy(row.contents[1])
            for a in description_wo_links.findAll('a'):
                a.decompose()
            description_wo_links = description_wo_links.text.strip()
            description_low = row.contents[1].text.strip().lower()
            self.graph.add((step_id, RDF.type, URIRef('Action')))
            self.graph.add((step_id, RDF.type, URIRef('bfo:process')))
            self.graph.add((step_id, RDF.type, URIRef('prov:Activity')))
            act_found = 0
            for indicator, ontology_class in activities.items():
                if indicator in description_low:
                    self.graph.add((step_id, OWL.sameAs, URIRef(ontology_class)))
                    act_found += 1
            if act_found == 0:
                self.log.error(
                    'Did not found specific activity for description: "%s"' % (description_text)
                )
            elif act_found > 1:
                self.log.warn('Found multiple activities for description: "%s"' % (description_text))

            try:
                start_time = datetime.strptime(row.contents[3].text, '%H:%M')
                self.graph.add((
                    step_id,
                    URIRef('startTime'),
                    Literal(start_time.strftime('%H:%M:%S'), datatype=XSD.time)
                ))
            except ValueError:
                self.graph.add((
                    step_id,
                    URIRef('startTime'),
                    Literal(row.contents[3].text, datatype=XSD.string)
                ))

            if idx > 1:
                self.graph.add((
                    step_id,
                    URIRef('prov:wasInformedBy'),
                    self.id_generator.getProtocolStep(id_prefix, idx-1)
                ))

            self.graph.add((section_id, URIRef('hasPart'), step_id))
            self.graph.add((
                step_id,
                URIRef('description'),
                Literal(description_text.replace('\n', '\\n'), lang='en')
            ))

            self._model_parameters(step_id, description_wo_links)

            # if the description contains further structure, iterate over contents
            used_items = []
            if row.contents[1].find_all(["ol", "ul"]):
                for element_part in row.contents[1].contents:
                    used_items += self._model_general_part(element_part)
            else:
                used_items += self._model_general_part(row.contents[1])

            # now, add all the used items to this step:
            for item_id in used_items:
                self.graph.add((
                    step_id,
                    URIRef('prov:used'),
                    item_id
                ))

            # however, for the linking of files, we want to search in the overall list
            for link in row.contents[1].find_all('a'):
                if link['href'].startswith('app/download.php'):
                    parsed_link = parse.urlparse(link['href'])
                    parsed_name = parse.parse_qs(parsed_link.query)['name'][0]
                    self.graph.add((
                        self.id_generator.getFile('Data/' + parsed_name),
                        URIRef('prov:wasGeneratedBy'),
                        step_id
                    )) # TODO: we assume that name will be represented only once

    def write_crate(self, target_archive):
        self.graph.serialize(
            format="json-ld",
            context=self.graph_context,
            destination=os.path.join(self.tempfolder, 'ro-crate-metadata.json')
        )
        shutil.make_archive(target_archive, 'zip', self.tempfolder)

    def __del__(self):
        shutil.rmtree(self.tempfolder)
