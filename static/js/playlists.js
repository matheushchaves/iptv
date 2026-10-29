// Janela "Listas": escolher, adicionar (link ou arquivo) e remover playlists.
import { $, esc } from "./util.js";
import { api } from "./api.js";

const select = $("#playlist");
const dlg = $("#dlg");
const FILE_HINT = "Escolher arquivo .m3u / .m3u8";
let pickedFile = null;

export async function refreshPlaylists(selected) {
  const playlists = await api.playlists();
  const target = playlists.some((p) => p.id === selected) ? selected : (playlists[0] || {}).id;
  select.innerHTML = playlists.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
  $("#saved").innerHTML = playlists.length ? playlists.map((p) => `
    <div class="saved-item"><div>${esc(p.name)}<small>${esc(p.source)}</small></div>
    <button class="btn danger" type="button" data-del="${esc(p.id)}">Remover</button></div>`).join("")
    : `<p class="note">Nenhuma lista salva.</p>`;
  if (target) select.value = target;
  return target;
}

const srcMode = () => document.querySelector('input[name="src"]:checked').value;

function setFile(file) {
  pickedFile = file || null;
  $("#fileLabel").textContent = file ? `${file.name} (${(file.size / 1048576).toFixed(1)} MB)` : FILE_HINT;
}

function resetForm() {
  $("#addForm").reset();
  setFile(null);
  $("#srcUrl").hidden = false;
  $("#srcFile").hidden = true;
}

async function submit(e, onSelect) {
  e.preventDefault();
  const msg = $("#formMsg"), btn = $("#addBtn"), name = $("#plName").value;
  msg.className = "";
  msg.textContent = "";
  try {
    let created;
    if (srcMode() === "file") {
      if (!pickedFile) throw new Error("Escolha um arquivo");
      btn.disabled = true;
      msg.className = "ok";
      msg.textContent = "Enviando arquivo…";
      created = await api.uploadPlaylist(name, pickedFile);
    } else {
      if (!$("#plUrl").value.trim()) throw new Error("Informe o link da lista");
      created = await api.addPlaylist(name, $("#plUrl").value);
    }
    resetForm();
    msg.textContent = "";
    await refreshPlaylists(created.id);
    dlg.close();
    onSelect(created.id);
  } catch (err) {
    msg.className = "";
    msg.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

async function remove(e, onSelect) {
  const btn = e.target.closest("[data-del]");
  const id = btn && btn.dataset.del;
  if (!id) return;
  try {
    const wasCurrent = select.value === id;
    await api.removePlaylist(id);
    const target = await refreshPlaylists(select.value);
    if (!target) onSelect(null);
    else if (wasCurrent) onSelect(target);
  } catch (err) {
    $("#formMsg").textContent = err.message;
  }
}

export function initPlaylists({ onSelect }) {
  select.addEventListener("change", () => onSelect(select.value));
  $("#manage").addEventListener("click", () => { $("#formMsg").textContent = ""; dlg.showModal(); });
  $("#close").addEventListener("click", () => dlg.close());
  document.querySelectorAll('input[name="src"]').forEach((r) => r.addEventListener("change", () => {
    $("#srcUrl").hidden = srcMode() !== "url";
    $("#srcFile").hidden = srcMode() !== "file";
    $("#formMsg").textContent = "";
  }));
  $("#plFile").addEventListener("change", (e) => setFile(e.target.files[0]));
  const drop = $(".drop");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); setFile(e.dataTransfer.files[0]); });
  $("#addForm").addEventListener("submit", (e) => submit(e, onSelect));
  $("#saved").addEventListener("click", (e) => remove(e, onSelect));
}
