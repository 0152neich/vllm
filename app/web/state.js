export const state = {
  managementKey: "",
  projects: [],
  models: [],
  selectedProjectId: "",
  currentRoute: "overview",
  issuedPlaintext: "",
  rawPlaygroundResponse: null,
  showRawResponse: false,
  principal: null,
};

export const MANAGEMENT_KEY_STORAGE = "llm_gateway_management_key";
export const THEME_STORAGE = "llm_gateway_theme";

export function selectedProject() {
  return state.projects.find((project) => project.id === state.selectedProjectId) || null;
}
