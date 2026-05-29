import { API_PREFIX } from "../constants.js";
import { mountGlossariesFeature } from "../features/glossaries/controller.js";
import {
  createGlossary,
  deleteGlossary,
  exportGlossaryCsv,
  fetchGlossaries,
  fetchGlossary,
  parseGlossaryCsv,
  updateGlossary,
} from "../api/glossaries.js";

export function mountGlossaryFeature(features) {
  features.glossariesFeature = mountGlossariesFeature({
    apiPrefix: API_PREFIX,
    fetchGlossaries,
    fetchGlossary,
    createGlossary,
    updateGlossary,
    deleteGlossary,
    exportGlossaryCsv,
    parseGlossaryCsv,
    refreshWorkflowGlossaries: (options) => features.workflowFeature?.loadGlossaryOptions(options),
  });
}
