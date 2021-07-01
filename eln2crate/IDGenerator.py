from rdflib import URIRef

class IDGenerator:
    def __init__(self, general_namespace, protocol_namespace):
        self.general_namespace = general_namespace
        self.protocol_namespace = protocol_namespace

    def getResearcher(self, researcher_key, researcher):
        if researcher.get('orcid'):
            return URIRef(researcher['orcid'])

        researcher_key = researcher_key.replace(' ', '_')
        researcher_key = researcher_key.replace('ä', 'ae')
        researcher_key = researcher_key.replace('ö', 'oe')
        researcher_key = researcher_key.replace('ü', 'ue')
        researcher_key = researcher_key.replace('ß', 'ss')
        researcher_id = 'researcher/%s' % (researcher_key)

        return URIRef(self.general_namespace[researcher_id])

    def getInstitution(self, institution_key, institution):
        if institution.get('ror'):
            return URIRef(institution.get('ror'))

        institution_id = 'institution/%s' % (institution_key)

        return URIRef(self.general_namespace[institution_id])

    def getManufacturer(self, manufacturer_key, manufacturer):
        if manufacturer.get('id'):
            return URIRef(manufacturer.get('id'))

        manufacturer_key = manufacturer_key.replace(' ', '_')
        manufacturer_id = 'manufacturer/%s' % (manufacturer_key)

        return URIRef(self.general_namespace[manufacturer_id])

    def getDataset(self):
        return URIRef('./')

    def getDBItem(self, item):
        item_id = 'database/%s' % (item['id'])

        return URIRef(self.general_namespace[item_id])

    def getDBLotInstance(self, item, lot_number):
        item_id = 'database/%s/lot/%s' % (item['id'], lot_number)

        return URIRef(self.general_namespace[item_id])

    def getDBLotPassageInstance(self, item, lot_number, passage_number):
        item_id = 'database/%s/lot/%s/passage/%s' % (item['id'], lot_number, passage_number)

        return URIRef(self.general_namespace[item_id])

    def getTemplate(self, template_key):
        temp_id = 'template/%s' % (template_key)

        return URIRef(self.general_namespace[temp_id])

    def getSectionTemplate(self, template_key):
        temp_id = 'template/%s' % (template_key)

        return URIRef(self.general_namespace[temp_id])

    def getLicense(self, license_name):
        license_id = 'license/%s' % (license_name)

        return URIRef(self.general_namespace[license_id])

    def getFile(self, filepath):
        return URIRef(filepath.replace(' ', '%20'))

    def getObjective(self):
        # NOTE: we assume there is only one objective
        return URIRef(self.protocol_namespace.objective)

    def getProtocol(self):
        return URIRef(self.protocol_namespace['protocol'])

    def getProtocolSection(self, section):
        return URIRef(self.protocol_namespace[section])

    def getProtocolStep(self, section, step_number):
        return URIRef(self.protocol_namespace['%s/%s' % (section, step_number)])

    def getMixture(self, ingredients, number):
        return URIRef(self.protocol_namespace['mixture/%s/%i' % (ingredients, number)])

    def getMixtureCreating(self, ingredients, number):
        return URIRef(self.protocol_namespace['mixture/%s/%i/creating' % (ingredients, number)])

    def getMixturePlan(self, ingredients, number):
        return URIRef(self.protocol_namespace['mixture/%s/plan/%i' % (ingredients, number)])