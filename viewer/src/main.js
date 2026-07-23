import * as OBC from "@thatopen/components";
import * as OBF from "@thatopen/components-front";

import "./style.css";

const message = document.getElementById("message");
const selection = document.getElementById("selection");
const container = document.getElementById("viewer");
const params = new URLSearchParams(window.location.search);
const projectId = params.get("project_id");
const modelVersion = params.get("v") || "unknown";

function firstSelectedItem(modelIdMap) {
  for (const [modelId, localIds] of Object.entries(modelIdMap)) {
    for (const localId of localIds) {
      return { modelId, localId: Number(localId) };
    }
  }
  return null;
}

async function selectedIfcReference(modelIdMap, fragments) {
  const selected = firstSelectedItem(modelIdMap);
  if (!selected || !Number.isInteger(selected.localId)) {
    throw new Error("the clicked geometry could not be mapped to an IFC entity");
  }

  const model = fragments.list.get(selected.modelId);
  if (model) {
    const [globalId] = await model.getGuidsByLocalIds([selected.localId]);
    if (globalId) return { global_id: globalId };
  }
  return { step_id: selected.localId };
}

async function saveSelection(ifcReference) {
  const saved = await fetch("/selection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    keepalive: true,
    body: JSON.stringify({
      project_id: Number(projectId),
      ...ifcReference,
    }),
  });
  if (!saved.ok) {
    throw new Error("the selection service rejected the selected IFC entity");
  }
  return saved.json();
}

async function frameModel(world, model) {
  const box = model.box.clone();
  if (box.isEmpty()) throw new Error("The Fragments model has no renderable geometry");

  const camera = world.camera.three;
  const center = box.getCenter(camera.position.clone());
  const size = box.getSize(camera.position.clone());
  const radius = Math.max(size.length() / 2, 1);

  await world.camera.controls.setLookAt(
    center.x + 1,
    center.y + 1,
    center.z + 1,
    center.x,
    center.y,
    center.z,
    false,
  );
  await world.camera.controls.fitToBox(box, false, {
    paddingTop: 0.6,
    paddingRight: 0.6,
    paddingBottom: 0.6,
    paddingLeft: 0.6,
  });
  world.camera.controls.update(0);

  const updateClippingPlanes = () => {
    const target = world.camera.controls.getTarget();
    const currentDistance = camera.position.distanceTo(target);
    camera.near = Math.max(0.01, Math.min(10, currentDistance / 10_000));
    camera.far = Math.max(1_000, currentDistance + radius * 2.5);
    camera.updateProjectionMatrix();
  };
  updateClippingPlanes();
  world.camera.controls.addEventListener("update", updateClippingPlanes);
}

async function loadModel() {
  if (!projectId) throw new Error("Missing project_id");

  const components = new OBC.Components();
  const worlds = components.get(OBC.Worlds);
  const world = worlds.create();
  world.scene = new OBC.SimpleScene(components);
  world.scene.setup();
  world.renderer = new OBC.SimpleRenderer(components, container);
  world.camera = new OBC.OrthoPerspectiveCamera(components);
  components.init();

  const grids = components.get(OBC.Grids);
  grids.create(world);

  const fragments = components.get(OBC.FragmentsManager);
  fragments.init(new URL("/fragments-worker.mjs", window.location.origin).href);

  const highlighter = components.get(OBF.Highlighter);
  highlighter.setup({ world });

  message.textContent = `Preparing optimized model (${modelVersion})...`;
  const response = await fetch(
    `/fragment?project_id=${encodeURIComponent(projectId)}&v=${encodeURIComponent(modelVersion)}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Fragments request failed: ${response.status}`);
  }

  message.textContent = "Loading optimized model...";
  const buffer = await response.arrayBuffer();
  const model = await fragments.core.load(buffer, {
    modelId: `project-${projectId}-${modelVersion}`,
    camera: world.camera.three,
  });
  model.useCamera(world.camera.three);
  world.scene.three.add(model.object);
  await frameModel(world, model);
  await fragments.core.update(true);
  world.camera.controls.addEventListener("update", () => {
    void fragments.core.update();
  });
  world.renderer.three.render(world.scene.three, world.camera.three);

  highlighter.events.select.onHighlight.add(async (modelIdMap) => {
    try {
      const ifcReference = await selectedIfcReference(modelIdMap, fragments);
      const entity = await saveSelection(ifcReference);
      selection.hidden = false;
      selection.textContent =
        `Selected: ${entity.ifc_type} #${entity.step_id}` +
        (entity.name ? ` — ${entity.name}` : "");
    } catch (error) {
      selection.hidden = false;
      selection.textContent = `Selection was not saved: ${error.message}`;
      console.error("Unable to save IFC selection", error);
    }
  });

  container.dataset.modelLoaded = "true";
  message.textContent = `Loaded optimized model (${modelVersion})`;
  setTimeout(() => message.remove(), 1800);
}

loadModel().catch((error) => {
  message.textContent = `Viewer failed: ${error.message}`;
  console.error(error);
});
