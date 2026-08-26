#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HELPER_PATH = Path("frontend/app/composables/use-mealplan-leftovers.ts")
EDIT_PATH = Path("frontend/app/pages/household/mealplan/planner/edit.vue")
VIEW_PATH = Path("frontend/app/pages/household/mealplan/planner/view.vue")
PLANNER_PATH = Path("frontend/app/pages/household/mealplan/planner.vue")
ENTRY_DIALOG_PATH = Path("frontend/app/components/Domain/Household/GroupMealPlanEntryDialog.vue")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.json"
DEFAULT_LOCALES_DIR = PROJECT_ROOT / "locales"

PROJECT_CONFIG: dict[str, Any] = {}
PROJECT_LOCALES_DIR = DEFAULT_LOCALES_DIR

HELPER_TEMPLATE = r'''import type { ReadPlanEntry } from "~/lib/api/types/meal-plan";

export const MEALPLAN_LEFTOVER_PREFIX = "mealie-weekly-leftovers:v1|";
export const MEALPLAN_LEFTOVER_LEGACY_WEEK_PREFIX = "tuxinet:mealplan:leftovers-week:v3|";
export const MEALPLAN_LEFTOVER_LEGACY_PREFIX = "tuxinet:mealplan:leftover:v1|";
export const LEFTOVER_WEEK_RECIPE_NAME = __RECIPE_NAME__;

export type MealplanLeftoverSource = {
  id: number;
  date: string;
  name: string;
};

export type MealplanLeftoverMeta = {
  mode: "week" | "legacy";
  sources: MealplanLeftoverSource[];
  note: string;
};

type MealplanLike = Pick<ReadPlanEntry, "text" | "recipeId">;

export function encodeMealplanLeftover(sources: MealplanLeftoverSource[], note: string): string {
  return `${MEALPLAN_LEFTOVER_PREFIX}${JSON.stringify({ sources, note: note.trim() })}`;
}

function parseWeekPayload(payload: string): MealplanLeftoverMeta | null {
  try {
    const parsed = JSON.parse(payload) as {
      sources?: MealplanLeftoverSource[];
      note?: string;
    };
    const sources = Array.isArray(parsed.sources)
      ? parsed.sources.filter(source => Number.isInteger(source.id) && source.id > 0 && /^\d{4}-\d{2}-\d{2}$/.test(source.date))
      : [];
    if (!sources.length) return null;
    return {
      mode: "week",
      sources,
      note: typeof parsed.note === "string" ? parsed.note : "",
    };
  }
  catch {
    return null;
  }
}

export function parseMealplanLeftover(meal: MealplanLike): MealplanLeftoverMeta | null {
  if (!meal.recipeId || !meal.text) return null;

  for (const prefix of [MEALPLAN_LEFTOVER_PREFIX, MEALPLAN_LEFTOVER_LEGACY_WEEK_PREFIX]) {
    if (meal.text.startsWith(prefix)) {
      return parseWeekPayload(meal.text.slice(prefix.length));
    }
  }

  if (meal.text.startsWith(MEALPLAN_LEFTOVER_LEGACY_PREFIX)) {
    const payload = meal.text.slice(MEALPLAN_LEFTOVER_LEGACY_PREFIX.length);
    const separator = payload.indexOf("|");
    if (separator <= 0) return null;
    const sourceId = Number(payload.slice(0, separator));
    const sourceDate = payload.slice(separator + 1);
    if (!Number.isInteger(sourceId) || sourceId <= 0 || !/^\d{4}-\d{2}-\d{2}$/.test(sourceDate)) return null;
    return {
      mode: "legacy",
      sources: [{ id: sourceId, date: sourceDate, name: "" }],
      note: "",
    };
  }

  return null;
}

export function isMealplanLeftover(meal: MealplanLike): boolean {
  return parseMealplanLeftover(meal) !== null;
}
'''

def fail(message: str) -> None:
    raise RuntimeError(message)

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)

def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing {label}: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"{label} must contain a JSON object: {path}")
    return data

def configure_project(config_path: Path, locales_dir: Path) -> None:
    global PROJECT_CONFIG, PROJECT_LOCALES_DIR
    config = load_json_object(config_path, "project config")
    default_locale = str(config.get("default_locale", "da-DK"))
    fallback_locale = str(config.get("fallback_locale", "en-US"))
    default_strings = load_json_object(locales_dir / f"{default_locale}.json", "default locale")
    load_json_object(locales_dir / f"{fallback_locale}.json", "fallback locale")
    recipe_name = config.get("recipe_name") or default_strings.get("leftovers-week-recipe")
    if not isinstance(recipe_name, str) or not recipe_name.strip():
        fail("recipe_name must be a non-empty string or resolvable from the default locale")
    PROJECT_CONFIG = {
        **config,
        "default_locale": default_locale,
        "fallback_locale": fallback_locale,
        "recipe_name": recipe_name.strip(),
    }
    PROJECT_LOCALES_DIR = locales_dir

def build_helper_content() -> str:
    return HELPER_TEMPLATE.replace(
        "__RECIPE_NAME__",
        json.dumps(PROJECT_CONFIG["recipe_name"], ensure_ascii=False),
    )

def patch_planner(text: str) -> str:
    text = replace_once(
        text,
        'import { useUserApi } from "~/composables/api";',
        'import { useUserApi } from "~/composables/api";\nimport { isMealplanLeftover } from "~/composables/use-mealplan-leftovers";',
        "planner import",
    )
    text = replace_once(
        text,
        'return mealsByDate.value.some(day => day.meals.some(meal => meal.recipe));',
        'return mealsByDate.value.some(day => day.meals.some(meal => meal.recipe && !isMealplanLeftover(meal)));',
        "planner hasRecipes",
    )
    text = replace_once(
        text,
        '''      if (meal.recipe) {
        allRecipes.push(meal.recipe);
      }''',
        '''      if (meal.recipe && !isMealplanLeftover(meal)) {
        allRecipes.push(meal.recipe);
      }''',
        "planner Add All filter",
    )
    return text

def patch_view(text: str) -> str:
    text = replace_once(
        text,
        'import type { RecipeSummary } from "~/lib/api/types/recipe";',
        'import type { RecipeSummary } from "~/lib/api/types/recipe";\nimport { isMealplanLeftover, parseMealplanLeftover } from "~/composables/use-mealplan-leftovers";',
        "view leftover import",
    )
    text = replace_once(
        text,
        ':description="mealplan.recipe ? mealplan.recipe.description! : mealplan.text!"',
        ':description="mealDescription(mealplan)"',
        "view description",
    )
    text = replace_once(
        text,
        ':name="mealplan.recipe ? mealplan.recipe.name! : mealplan.title!"',
        ':name="mealName(mealplan)"',
        "view name",
    )
    text = replace_once(
        text,
        '''            :tags="mealplan.recipe ? mealplan.recipe.tags! : []"
          />''',
        '''            :tags="mealplan.recipe ? mealplan.recipe.tags! : []"
          >
            <template v-if="isMealplanLeftover(mealplan)" #actions>
              <v-card-actions class="w-100 justify-end my-0 px-2 py-0">
                <v-chip size="small" color="secondary">
                  <v-icon start>
                    mdi-recycle
                  </v-icon>
                  {{ i18n.t("meal-plan.leftovers") }}
                </v-chip>
              </v-card-actions>
            </template>
          </RecipeCardMobile>''',
        "view leftover badge",
    )
    text = replace_once(
        text,
        '      recipes: day.meals.flatMap(meal => meal.recipe ?? []),',
        '      recipes: day.meals.flatMap(meal => meal.recipe && !isMealplanLeftover(meal) ? [meal.recipe] : []),',
        "view day recipe filter",
    )

    anchor = '''const isToday = (date: Date) => {
  return isSameDay(date, new Date());
};'''
    helpers = '''function formatLeftoverDate(date: string) {
  try {
    return i18n.d(new Date(`${date}T12:00:00`), "short");
  }
  catch {
    return date;
  }
}

function mealName(mealplan: ReadPlanEntry) {
  const meta = parseMealplanLeftover(mealplan);
  if (meta?.mode === "week") {
    return mealplan.recipe?.name || i18n.t("meal-plan.leftovers-week-recipe");
  }
  const baseName = mealplan.recipe ? mealplan.recipe.name! : mealplan.title!;
  return meta ? `${i18n.t("meal-plan.leftovers")}: ${baseName}` : baseName;
}

function mealDescription(mealplan: ReadPlanEntry) {
  const meta = parseMealplanLeftover(mealplan);
  if (!meta) {
    return mealplan.recipe ? mealplan.recipe.description! : mealplan.text!;
  }
  if (meta.mode === "legacy") {
    return `${i18n.t("meal-plan.leftovers-from")} ${formatLeftoverDate(meta.sources[0].date)}`;
  }
  const byDate = new Map<string, string[]>();
  for (const source of meta.sources) {
    const names = byDate.get(source.date) || [];
    if (source.name && !names.includes(source.name)) names.push(source.name);
    byDate.set(source.date, names);
  }
  const sourceText = Array.from(byDate.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, names]) => `${formatLeftoverDate(date)}${names.length ? `: ${names.join(", ")}` : ""}`)
    .join(" · ");
  const noteText = meta.note.trim() ? ` · ${i18n.t("meal-plan.leftovers-note")}: ${meta.note.trim()}` : "";
  return `${i18n.t("meal-plan.leftovers-from")}: ${sourceText}${noteText}`;
}

const isToday = (date: Date) => {
  return isSameDay(date, new Date());
};'''
    return replace_once(text, anchor, helpers, "view display helpers")

def patch_edit(text: str) -> str:
    return replace_once(
        text,
        '''      :entry="dialog.entry"
      :date="dialog.date"
      @create="actions.createOne($event)"''',
        '''      :entry="dialog.entry"
      :date="dialog.date"
      :mealplans="mealplans"
      @create="actions.createOne($event)"''',
        "edit pass mealplans",
    )

def patch_entry_dialog(text: str) -> str:
    text = replace_once(
        text,
        '''            <v-btn
              value="note"
              class="flex-grow-1"
            >''',
        '''            <v-btn
              value="leftover"
              class="flex-grow-1"
            >
              <v-icon start>
                mdi-recycle
              </v-icon>
              {{ $t("meal-plan.leftovers") }}
            </v-btn>
            <v-btn
              value="note"
              class="flex-grow-1"
            >''',
        "dialog leftover tab",
    )

    leftover_panel = '''          <v-card
            v-else-if="isLeftover"
            variant="tonal"
          >
            <v-card-title class="text-subtitle-1 d-flex align-center flex-wrap ga-2">
              <v-icon>mdi-recycle</v-icon>
              {{ $t("meal-plan.leftovers-week-recipe") }}
              <v-chip class="ml-auto" size="small" color="secondary" variant="tonal">
                {{ $t("meal-plan.leftovers-selected-days", { count: leftoverSelectedDates.length }) }}
              </v-chip>
            </v-card-title>
            <v-card-subtitle class="text-wrap pb-2">
              {{ $t("meal-plan.leftovers-select-source-days") }}
            </v-card-subtitle>
            <v-card-actions class="px-4 pt-0 flex-wrap ga-2">
              <v-btn size="small" color="secondary" variant="tonal" @click="selectAllLeftoverDays">
                <v-icon start>mdi-calendar-multiple</v-icon>
                {{ $t("meal-plan.leftovers-select-all-week") }}
              </v-btn>
              <v-btn size="small" variant="text" @click="clearLeftoverDays">
                {{ $t("meal-plan.leftovers-clear") }}
              </v-btn>
            </v-card-actions>
            <v-list v-if="leftoverDayCandidates.length" bg-color="transparent" density="compact">
              <v-list-item
                v-for="day in leftoverDayCandidates"
                :key="day.date"
                @click="toggleLeftoverDate(day.date)"
              >
                <template #prepend>
                  <v-checkbox-btn
                    :model-value="leftoverSelectedDates.includes(day.date)"
                    readonly
                    color="secondary"
                  />
                </template>
                <v-list-item-title>{{ day.label }}</v-list-item-title>
                <v-list-item-subtitle class="text-wrap">
                  {{ day.recipeNames.join(" · ") }}
                </v-list-item-subtitle>
              </v-list-item>
            </v-list>
            <v-alert v-else type="info" variant="tonal" class="ma-3">
              {{ $t("meal-plan.no-leftovers-available") }}
            </v-alert>
            <v-card-text class="pt-2">
              <v-textarea
                v-model="leftoverNote"
                rows="2"
                auto-grow
                :label="$t('meal-plan.leftovers-note')"
                :hint="$t('meal-plan.leftovers-note-hint')"
                persistent-hint
              />
            </v-card-text>
          </v-card>

'''
    text = replace_once(
        text,
        '''          <div v-else>
            <v-text-field''',
        leftover_panel + '''          <div v-else>
            <v-text-field''',
        "dialog leftover panel",
    )

    text = replace_once(
        text,
        'import { validators } from "~/composables/use-validators";',
        'import { validators } from "~/composables/use-validators";\nimport { useUserApi } from "~/composables/api";\nimport { LEFTOVER_WEEK_RECIPE_NAME, encodeMealplanLeftover, isMealplanLeftover, parseMealplanLeftover } from "~/composables/use-mealplan-leftovers";',
        "dialog leftover imports",
    )
    text = replace_once(
        text,
        '''interface Props {
  entry?: ReadPlanEntry | null;
  date?: Date | null;
}''',
        '''interface Props {
  entry?: ReadPlanEntry | null;
  date?: Date | null;
  mealplans?: Array<{ date: Date; meals: ReadPlanEntry[] }>;
}''',
        "dialog props",
    )
    text = replace_once(
        text,
        '''const props = withDefaults(defineProps<Props>(), {
  entry: null,
  date: null,
});''',
        '''const props = withDefaults(defineProps<Props>(), {
  entry: null,
  date: null,
  mealplans: () => [],
});''',
        "dialog prop defaults",
    )
    text = replace_once(
        text,
        'const planTypeOptions = usePlanTypeOptions();',
        'const planTypeOptions = usePlanTypeOptions();\nconst api = useUserApi();\nconst i18n = useI18n();',
        "dialog api",
    )
    text = replace_once(
        text,
        'const entryMode = ref<"recipe" | "note">("recipe");',
        'const entryMode = ref<"recipe" | "leftover" | "note">("recipe");',
        "dialog mode type",
    )
    text = replace_once(
        text,
        '''const text = ref("");
const ignoreRules = ref(false);''',
        '''const text = ref("");
const ignoreRules = ref(false);
const leftoverSelectedDates = ref<string[]>([]);
const leftoverNote = ref("");''',
        "dialog leftover state",
    )
    text = replace_once(
        text,
        '''const isRecipe = computed(() => entryMode.value === "recipe");
const firstDayOfWeek''',
        '''const isRecipe = computed(() => entryMode.value === "recipe");
const isLeftover = computed(() => entryMode.value === "leftover");
const firstDayOfWeek''',
        "dialog leftover computed",
    )
    text = replace_once(
        text,
        'const submitDisabled = computed(() => isRecipe.value ? !recipe.value : !title.value.trim());',
        '''const submitDisabled = computed(() => {
  if (isRecipe.value) return !recipe.value;
  if (isLeftover.value) return selectedLeftoverSources.value.length === 0;
  return !title.value.trim();
});''',
        "dialog submit disabled",
    )

    logic_anchor = '''function parseEntryDate(date: string) {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year, month - 1, day);
}'''
    logic = '''function selectedDateString() {
  return format(selectedDate.value, "yyyy-MM-dd");
}

function formatLeftoverDate(date: string) {
  try {
    return i18n.d(new Date(`${date}T12:00:00`), "short");
  }
  catch {
    return date;
  }
}

const leftoverDayCandidates = computed(() => {
  const targetDate = selectedDateString();
  return props.mealplans
    .map((plan) => {
      const date = format(plan.date, "yyyy-MM-dd");
      const meals = (plan.meals ?? []).filter(meal =>
        meal.recipe
        && !isMealplanLeftover(meal)
        && meal.recipe.name !== LEFTOVER_WEEK_RECIPE_NAME,
      );
      return {
        date,
        label: formatLeftoverDate(date),
        meals,
        recipeNames: meals.map(meal => meal.recipe?.name || meal.title || "").filter(Boolean),
      };
    })
    .filter(day => day.date < targetDate && day.meals.length > 0)
    .sort((a, b) => a.date.localeCompare(b.date));
});

const selectedLeftoverSources = computed(() => {
  const selected = new Set(leftoverSelectedDates.value);
  return leftoverDayCandidates.value
    .filter(day => selected.has(day.date))
    .flatMap(day => day.meals.map(meal => ({
      id: meal.id,
      date: meal.date,
      name: meal.recipe?.name || meal.title || "",
    })));
});

function toggleLeftoverDate(date: string) {
  if (leftoverSelectedDates.value.includes(date)) {
    leftoverSelectedDates.value = leftoverSelectedDates.value.filter(item => item !== date);
  }
  else {
    leftoverSelectedDates.value = [...leftoverSelectedDates.value, date].sort();
  }
}

function selectAllLeftoverDays() {
  leftoverSelectedDates.value = leftoverDayCandidates.value.map(day => day.date);
}

function clearLeftoverDays() {
  leftoverSelectedDates.value = [];
}

async function ensureLeftoverWeekRecipe() {
  const normalize = (value: string | null | undefined) => (value || "").trim().toLocaleLowerCase();
  const exactName = normalize(LEFTOVER_WEEK_RECIPE_NAME);
  const findExisting = async () => {
    const { data } = await api.recipes.search({ search: LEFTOVER_WEEK_RECIPE_NAME, perPage: 50 });
    return data?.items.find(item => normalize(item.name) === exactName);
  };
  const existing = await findExisting();
  if (existing?.id) return existing;

  const created = await api.recipes.createOne({ name: LEFTOVER_WEEK_RECIPE_NAME });
  const createdData = created.data as any;
  if (createdData && typeof createdData === "object" && createdData.id) return createdData;

  const slug = typeof createdData === "string"
    ? createdData
    : typeof created.response?.data === "string"
      ? created.response.data
      : null;
  if (slug) {
    const { data: createdRecipe } = await api.recipes.getOne(slug);
    if (createdRecipe?.id) return createdRecipe;
  }
  const retry = await findExisting();
  if (retry?.id) return retry;
  throw new Error(`Could not create or find ${LEFTOVER_WEEK_RECIPE_NAME}`);
}

function parseEntryDate(date: string) {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year, month - 1, day);
}'''
    text = replace_once(text, logic_anchor, logic, "dialog leftover logic")

    old_initialize = '''function initialize() {
  entryMode.value = props.entry && !props.entry.recipeId ? "note" : "recipe";
  selectedDate.value = props.entry ? parseEntryDate(props.entry.date) : props.date ?? new Date();
  entryType.value = props.entry?.entryType ?? "dinner";
  recipe.value = props.entry?.recipe ?? null;
  title.value = props.entry?.title ?? "";
  text.value = props.entry?.text ?? "";
  ignoreRules.value = false;
  selector.value?.reset();
}'''
    new_initialize = '''function initialize() {
  const leftover = props.entry ? parseMealplanLeftover(props.entry) : null;
  entryMode.value = leftover ? "leftover" : props.entry && !props.entry.recipeId ? "note" : "recipe";
  selectedDate.value = props.entry ? parseEntryDate(props.entry.date) : props.date ?? new Date();
  entryType.value = props.entry?.entryType ?? "dinner";
  recipe.value = props.entry?.recipe ?? null;
  title.value = props.entry?.title ?? "";
  text.value = props.entry?.text ?? "";
  leftoverSelectedDates.value = leftover
    ? Array.from(new Set(leftover.sources.map(source => source.date))).sort()
    : [];
  leftoverNote.value = leftover?.note || "";
  ignoreRules.value = false;
  selector.value?.reset();
}'''
    text = replace_once(text, old_initialize, new_initialize, "dialog initialize")

    old_submit = '''function submit() {
  const payload = {
    date: format(selectedDate.value, "yyyy-MM-dd"),
    entryType: entryType.value,
    title: isRecipe.value ? "" : title.value,
    text: isRecipe.value ? "" : text.value,
    recipeId: isRecipe.value ? recipe.value?.id : null,
  };

  if (props.entry) {
    emit("update", {
      ...payload,
      id: props.entry.id,
      groupId: props.entry.groupId,
      userId: props.entry.userId,
    });
  }
  else {
    emit("create", payload);
  }
}'''
    new_submit = '''async function submit() {
  let payload;
  if (isLeftover.value) {
    const leftoverRecipe = await ensureLeftoverWeekRecipe();
    if (!leftoverRecipe?.id) throw new Error(`${LEFTOVER_WEEK_RECIPE_NAME} recipe has no id`);
    payload = {
      date: format(selectedDate.value, "yyyy-MM-dd"),
      entryType: entryType.value,
      title: "",
      text: encodeMealplanLeftover(selectedLeftoverSources.value, leftoverNote.value),
      recipeId: leftoverRecipe.id,
    };
  }
  else {
    payload = {
      date: format(selectedDate.value, "yyyy-MM-dd"),
      entryType: entryType.value,
      title: isRecipe.value ? "" : title.value,
      text: isRecipe.value ? "" : text.value,
      recipeId: isRecipe.value ? recipe.value?.id : null,
    };
  }

  if (props.entry) {
    emit("update", {
      ...payload,
      id: props.entry.id,
      groupId: props.entry.groupId,
      userId: props.entry.userId,
    });
  }
  else {
    emit("create", payload);
  }
}'''
    return replace_once(text, old_submit, new_submit, "dialog submit")

def patch_translations(root: Path, apply: bool) -> list[str]:
    locale_files = [p for p in sorted(PROJECT_LOCALES_DIR.glob("*.json")) if p.name != "TEMPLATE.json"]
    if not locale_files:
        fail(f"No locale JSON files found in: {PROJECT_LOCALES_DIR}")

    fallback_values = load_json_object(
        PROJECT_LOCALES_DIR / f"{PROJECT_CONFIG['fallback_locale']}.json",
        "fallback locale",
    )
    required_keys = {k for k, v in fallback_values.items() if isinstance(v, str)}
    changed: list[str] = []

    for source in locale_files:
        values = load_json_object(source, f"locale {source.stem}")
        string_values = {k: v for k, v in values.items() if isinstance(v, str)}
        missing = sorted(required_keys - set(string_values))
        if missing:
            fail(f"{source.name}: missing translation keys: {', '.join(missing)}")

        target = root / "frontend/app/lang/messages" / source.name
        if not target.exists():
            print(f"Skipping locale {source.stem}: Mealie does not ship {target.name}")
            continue

        data = json.loads(target.read_text(encoding="utf-8"))
        meal_plan = data.get("meal-plan")
        if not isinstance(meal_plan, dict):
            fail(f"{target.name}: missing meal-plan translation object")

        if any(meal_plan.get(k) != v for k, v in string_values.items()):
            changed.append(str(target.relative_to(root)))
            if apply:
                meal_plan.update(string_values)
                target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return changed

def run(root: Path, apply: bool) -> None:
    transforms = {
        PLANNER_PATH: patch_planner,
        VIEW_PATH: patch_view,
        EDIT_PATH: patch_edit,
        ENTRY_DIALOG_PATH: patch_entry_dialog,
    }

    for rel in transforms:
        if not (root / rel).exists():
            fail(f"Missing expected Mealie v3.24 source file: {rel}")

    changes: list[str] = []
    for rel, transform in transforms.items():
        path = root / rel
        before = path.read_text(encoding="utf-8")
        after = transform(before)
        if after != before:
            changes.append(str(rel))
            if apply:
                path.write_text(after, encoding="utf-8")

    helper = root / HELPER_PATH
    helper_content = build_helper_content()
    if not helper.exists() or helper.read_text(encoding="utf-8") != helper_content:
        changes.append(str(HELPER_PATH))
        if apply:
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text(helper_content, encoding="utf-8")

    changes.extend(patch_translations(root, apply))

    print("Mealie Weekly Leftovers v3.24 patch applied successfully." if apply else "Mealie Weekly Leftovers v3.24 compatibility check passed.")
    if changes:
        print("Changed files:" if apply else "Files that would change:")
        for item in sorted(set(changes)):
            print(f"  - {item}")
    else:
        print("Patch is already applied; no changes required.")

def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Mealie v3.24 Meal Planner with Weekly Leftovers support.")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--locales", type=Path, default=DEFAULT_LOCALES_DIR)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    try:
        configure_project(args.config.resolve(), args.locales.resolve())
        run(args.root.resolve(), args.apply)
    except Exception as exc:
        print(f"Weekly Leftovers v3.24 patch FAILED: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
