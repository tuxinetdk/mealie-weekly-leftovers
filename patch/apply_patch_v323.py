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
    if (!sources.length) {
      return null;
    }
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
  if (!meal.recipeId || !meal.text) {
    return null;
  }

  for (const prefix of [MEALPLAN_LEFTOVER_PREFIX, MEALPLAN_LEFTOVER_LEGACY_WEEK_PREFIX]) {
    if (meal.text.startsWith(prefix)) {
      return parseWeekPayload(meal.text.slice(prefix.length));
    }
  }

  if (meal.text.startsWith(MEALPLAN_LEFTOVER_LEGACY_PREFIX)) {
    const payload = meal.text.slice(MEALPLAN_LEFTOVER_LEGACY_PREFIX.length);
    const separator = payload.indexOf("|");
    if (separator <= 0) {
      return null;
    }
    const sourceId = Number(payload.slice(0, separator));
    const sourceDate = payload.slice(separator + 1);
    if (!Number.isInteger(sourceId) || sourceId <= 0 || !/^\d{4}-\d{2}-\d{2}$/.test(sourceDate)) {
      return null;
    }
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

    default_locale_path = locales_dir / f"{default_locale}.json"
    fallback_locale_path = locales_dir / f"{fallback_locale}.json"
    default_strings = load_json_object(default_locale_path, "default locale")
    load_json_object(fallback_locale_path, "fallback locale")

    recipe_name = config.get("recipe_name")
    if recipe_name is None:
        recipe_name = default_strings.get("leftovers-week-recipe")

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
    recipe_name = json.dumps(PROJECT_CONFIG["recipe_name"], ensure_ascii=False)
    return HELPER_TEMPLATE.replace("__RECIPE_NAME__", recipe_name)

def fail(message: str) -> None:
    raise RuntimeError(message)

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)

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

    old_card = '''          <RecipeCardMobile
            v-for="mealplan in section.meals"
            :key="mealplan.id"
            :recipe-id="mealplan.recipe ? mealplan.recipe.id! : ''"
            class="mb-2"
            :rating="mealplan.recipe ? mealplan.recipe.rating! : 0"
            :slug="mealplan.recipe ? mealplan.recipe.slug! : mealplan.title!"
            :description="mealplan.recipe ? mealplan.recipe.description! : mealplan.text!"
            :name="mealplan.recipe ? mealplan.recipe.name! : mealplan.title!"
            :tags="mealplan.recipe ? mealplan.recipe.tags! : []"
          />'''
    new_card = '''          <RecipeCardMobile
            v-for="mealplan in section.meals"
            :key="mealplan.id"
            :recipe-id="mealplan.recipe ? mealplan.recipe.id! : ''"
            class="mb-2"
            :rating="mealplan.recipe ? mealplan.recipe.rating! : 0"
            :slug="mealplan.recipe ? mealplan.recipe.slug! : mealplan.title!"
            :description="mealDescription(mealplan)"
            :name="mealName(mealplan)"
            :tags="mealplan.recipe ? mealplan.recipe.tags! : []"
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
          </RecipeCardMobile>'''
    text = replace_once(text, old_card, new_card, "view recipe card")

    text = replace_once(
        text,
        '''      if (meal.recipe) {
        out.recipes.push(meal.recipe);
      }''',
        '''      if (meal.recipe && !isMealplanLeftover(meal)) {
        out.recipes.push(meal.recipe);
      }''',
        "view day shopping-list filter",
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
    const items = byDate.get(source.date) || [];
    if (source.name && !items.includes(source.name)) {
      items.push(source.name);
    }
    byDate.set(source.date, items);
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
    text = replace_once(text, anchor, helpers, "view display helpers")
    return text

def patch_edit(text: str) -> str:
    old_submit = '''      @submit="
        () => {
          if (newMeal.existing) {
            actions.updateOne({ ...newMeal, date: newMealDateString });
          }
          else {
            actions.createOne({ ...newMeal, date: newMealDateString });
          }
          resetDialog();
        }
      "'''
    text = replace_once(text, old_submit, '''      @submit="submitMeal"''', "edit submit handler")

    old_form = '''          <v-autocomplete
            v-if="!dialog.note"
            v-model="newMeal.recipeId"
            v-model:search="search.query.value"
            :label="$t('meal-plan.meal-recipe')"
            :items="search.data.value"
            :custom-filter="normalizeFilter"
            :loading="search.loading.value"
            cache-items
            item-title="name"
            item-value="id"
            :return-object="false"
            :rules="[requiredRule]"
          />
          <template v-else>
            <v-text-field v-model="newMeal.title" :rules="[requiredRule]" :label="$t('meal-plan.meal-title')" />
            <v-textarea v-model="newMeal.text" rows="2" :label="$t('meal-plan.meal-note')" />
          </template>
        </v-card-text>
        <v-card-actions class="py-0 px-4">
          <v-switch v-model="dialog.note" class="mt-n3 mb-n4" :label="$t('meal-plan.note-only')" />
        </v-card-actions>'''
    new_form = '''          <v-btn-toggle
            v-model="dialog.mode"
            mandatory
            divided
            class="mb-4 d-flex"
          >
            <v-btn value="recipe" class="flex-grow-1">
              {{ $t("meal-plan.meal-recipe") }}
            </v-btn>
            <v-btn value="leftover" class="flex-grow-1">
              <v-icon start>
                mdi-recycle
              </v-icon>
              {{ $t("meal-plan.leftovers") }}
            </v-btn>
            <v-btn value="note" class="flex-grow-1">
              {{ $t("meal-plan.note-only") }}
            </v-btn>
          </v-btn-toggle>

          <v-autocomplete
            v-if="dialog.mode === 'recipe'"
            v-model="newMeal.recipeId"
            v-model:search="search.query.value"
            :label="$t('meal-plan.meal-recipe')"
            :items="search.data.value"
            :custom-filter="normalizeFilter"
            :loading="search.loading.value"
            cache-items
            item-title="name"
            item-value="id"
            :return-object="false"
            :rules="[requiredRule]"
          />

          <v-card v-else-if="dialog.mode === 'leftover'" variant="tonal">
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

          <template v-else>
            <v-text-field v-model="newMeal.title" :rules="[requiredRule]" :label="$t('meal-plan.meal-title')" />
            <v-textarea v-model="newMeal.text" rows="2" :label="$t('meal-plan.meal-note')" />
          </template>
        </v-card-text>'''
    text = replace_once(text, old_form, new_form, "edit form")

    text = replace_once(
        text,
        '''              <v-list-item-title class="mb-1">
                {{ mealplan.recipe ? mealplan.recipe.name : mealplan.title }}
              </v-list-item-title>
              <v-list-item-subtitle style="min-height: 16px">
                {{ mealplan.recipe ? mealplan.recipe.description + " " : mealplan.text }}
              </v-list-item-subtitle>''',
        '''              <v-list-item-title class="mb-1">
                {{ mealEditTitle(mealplan) }}
              </v-list-item-title>
              <v-list-item-subtitle style="min-height: 16px" class="text-wrap">
                {{ mealEditSubtitle(mealplan) }}
              </v-list-item-subtitle>''',
        "edit card display",
    )

    text = replace_once(
        text,
        'import type { PlanEntryType, UpdatePlanEntry } from "~/lib/api/types/meal-plan";',
        'import type { PlanEntryType, ReadPlanEntry, UpdatePlanEntry } from "~/lib/api/types/meal-plan";',
        "edit type import",
    )
    text = replace_once(
        text,
        'import { useRecipeSearch } from "~/composables/recipes/use-recipe-search";',
        'import { useRecipeSearch } from "~/composables/recipes/use-recipe-search";\nimport type { Recipe } from "~/lib/api/types/recipe";\nimport { LEFTOVER_WEEK_RECIPE_NAME, encodeMealplanLeftover, isMealplanLeftover, parseMealplanLeftover } from "~/composables/use-mealplan-leftovers";',
        "edit leftover import",
    )
    text = replace_once(
        text,
        'const api = useUserApi();\nconst auth = useMealieAuth();',
        'const api = useUserApi();\nconst auth = useMealieAuth();\nconst i18n = useI18n();',
        "edit i18n",
    )

    old_dialog = '''const dialog = reactive({
  loading: false,
  error: false,
  note: false,
});

watch(dialog, () => {
  if (dialog.note) {
    newMeal.recipeId = undefined;
  }
});'''
    new_dialog = '''type MealDialogMode = "recipe" | "leftover" | "note";

const dialog = reactive({
  loading: false,
  error: false,
  mode: "recipe" as MealDialogMode,
});

const leftoverSelectedDates = ref<string[]>([]);
const leftoverNote = ref("");'''
    text = replace_once(text, old_dialog, new_dialog, "edit dialog state")

    old_computed = '''const newMealDateString = computed(() => {
  return format(newMeal.date, "yyyy-MM-dd");
});

const isCreateDisabled = computed(() => {
  if (dialog.note) {
    return !newMeal.title.trim();
  }
  return !newMeal.recipeId;
});'''
    new_computed = '''const newMealDateString = computed(() => {
  return format(newMeal.date, "yyyy-MM-dd");
});

function formatLeftoverDate(date: string) {
  try {
    return i18n.d(new Date(`${date}T12:00:00`), "short");
  }
  catch {
    return date;
  }
}

const allVisibleMeals = computed<ReadPlanEntry[]>(() => {
  return props.mealplans.flatMap(plan => plan.meals ?? []);
});

const leftoverDayCandidates = computed(() => {
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
    .filter(day => day.date < newMealDateString.value && day.meals.length > 0)
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

function mealEditTitle(mealplan: UpdatePlanEntry) {
  const meta = parseMealplanLeftover(mealplan);
  if (meta?.mode === "week") {
    return mealplan.recipe?.name || LEFTOVER_WEEK_RECIPE_NAME;
  }
  return mealplan.recipe ? mealplan.recipe.name : mealplan.title;
}

function mealEditSubtitle(mealplan: UpdatePlanEntry) {
  const meta = parseMealplanLeftover(mealplan);
  if (!meta) {
    return mealplan.recipe ? `${mealplan.recipe.description || ""} ` : mealplan.text;
  }
  const dates = Array.from(new Set(meta.sources.map(source => source.date)))
    .sort()
    .map(formatLeftoverDate)
    .join(", ");
  return meta.note.trim()
    ? `${i18n.t("meal-plan.leftovers-from")}: ${dates} · ${meta.note.trim()}`
    : `${i18n.t("meal-plan.leftovers-from")}: ${dates}`;
}

async function ensureLeftoverWeekRecipe(): Promise<Recipe> {
  const normalize = (value: string | null | undefined) => (value || "").trim().toLocaleLowerCase();
  const exactName = normalize(LEFTOVER_WEEK_RECIPE_NAME);

  const findExisting = async () => {
    const { data } = await api.recipes.search({ search: LEFTOVER_WEEK_RECIPE_NAME, perPage: 50 });
    return data?.items.find(recipe => normalize(recipe.name) === exactName);
  };

  const existing = await findExisting();
  if (existing?.id) {
    return existing;
  }

  const created = await api.recipes.createOne({ name: LEFTOVER_WEEK_RECIPE_NAME });
  const createdData = created.data as any;
  if (createdData && typeof createdData === "object" && createdData.id) {
    return createdData as Recipe;
  }

  const slug = typeof createdData === "string"
    ? createdData
    : typeof created.response?.data === "string"
      ? created.response.data
      : null;
  if (slug) {
    const { data: recipe } = await api.recipes.getOne(slug);
    if (recipe?.id) {
      return recipe;
    }
  }

  const retry = await findExisting();
  if (retry?.id) {
    return retry;
  }

  throw new Error(`Could not create or find ${LEFTOVER_WEEK_RECIPE_NAME}`);
}

watch(newMealDateString, (date) => {
  leftoverSelectedDates.value = leftoverSelectedDates.value.filter(sourceDate => sourceDate < date);
});

watch(
  () => dialog.mode,
  (mode) => {
    if (mode === "note") {
      newMeal.recipeId = undefined;
      leftoverSelectedDates.value = [];
      leftoverNote.value = "";
      if (isMealplanLeftover(newMeal)) {
        newMeal.text = "";
      }
    }
    else if (mode === "recipe") {
      leftoverSelectedDates.value = [];
      leftoverNote.value = "";
      if (isMealplanLeftover(newMeal)) {
        newMeal.text = "";
        newMeal.recipeId = undefined;
      }
      newMeal.title = "";
    }
    else {
      newMeal.title = "";
      if (!newMeal.existing) {
        newMeal.recipeId = undefined;
        newMeal.text = "";
      }
    }
  },
);

const isCreateDisabled = computed(() => {
  if (dialog.loading) {
    return true;
  }
  if (dialog.mode === "note") {
    return !newMeal.title.trim();
  }
  if (dialog.mode === "leftover") {
    return leftoverSelectedDates.value.length === 0 || selectedLeftoverSources.value.length === 0;
  }
  return !newMeal.recipeId;
});

async function submitMeal() {
  if (isCreateDisabled.value) {
    return;
  }

  dialog.loading = true;
  try {
    if (dialog.mode === "leftover") {
      const recipe = await ensureLeftoverWeekRecipe();
      if (!recipe.id) {
        throw new Error(`${LEFTOVER_WEEK_RECIPE_NAME} recipe has no id`);
      }

      const payload = {
        ...newMeal,
        date: newMealDateString.value,
        title: "",
        recipeId: recipe.id,
        text: encodeMealplanLeftover(selectedLeftoverSources.value, leftoverNote.value),
      };

      if (newMeal.existing) {
        await props.actions.updateOne(payload);
      }
      else {
        await props.actions.createOne(payload);
      }
      resetDialog();
      return;
    }

    if (newMeal.existing) {
      await props.actions.updateOne({ ...newMeal, date: newMealDateString.value });
    }
    else {
      await props.actions.createOne({ ...newMeal, date: newMealDateString.value });
    }
    resetDialog();
  }
  finally {
    dialog.loading = false;
  }
}'''
    text = replace_once(text, old_computed, new_computed, "edit leftovers logic")

    old_edit_reset = '''function editMeal(mealplan: UpdatePlanEntry) {
  const { date, title, text, entryType, recipeId, id, groupId, userId } = mealplan;
  if (!entryType) return;

  const [year, month, day] = date.split("-").map(Number);
  newMeal.date = new Date(year, month - 1, day);
  newMeal.title = title || "";
  newMeal.text = text || "";
  newMeal.recipeId = recipeId || undefined;
  newMeal.entryType = entryType;
  newMeal.existing = true;
  newMeal.id = id;
  newMeal.groupId = groupId;
  newMeal.userId = userId || auth.user.value?.id || "";

  state.value.dialog = true;
  dialog.note = !recipeId;
}

function resetDialog() {
  newMeal.date = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
  newMeal.title = "";
  newMeal.text = "";
  newMeal.entryType = "dinner";
  newMeal.recipeId = undefined;
  newMeal.existing = false;
}'''
    new_edit_reset = '''function editMeal(mealplan: UpdatePlanEntry) {
  const { date, title, text, entryType, recipeId, id, groupId, userId } = mealplan;
  if (!entryType) return;

  const [year, month, day] = date.split("-").map(Number);
  newMeal.date = new Date(year, month - 1, day);
  newMeal.title = title || "";
  newMeal.text = text || "";
  newMeal.recipeId = recipeId || undefined;
  newMeal.entryType = entryType;
  newMeal.existing = true;
  newMeal.id = id;
  newMeal.groupId = groupId;
  newMeal.userId = userId || auth.user.value?.id || "";

  const leftover = parseMealplanLeftover(mealplan);
  leftoverSelectedDates.value = leftover
    ? Array.from(new Set(leftover.sources.map(source => source.date))).sort()
    : [];
  leftoverNote.value = leftover?.note || "";
  dialog.mode = leftover ? "leftover" : recipeId ? "recipe" : "note";
  state.value.dialog = true;
}

function resetDialog() {
  newMeal.date = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
  newMeal.title = "";
  newMeal.text = "";
  newMeal.entryType = "dinner";
  newMeal.recipeId = undefined;
  newMeal.existing = false;
  leftoverSelectedDates.value = [];
  leftoverNote.value = "";
  dialog.mode = "recipe";
}'''
    text = replace_once(text, old_edit_reset, new_edit_reset, "edit edit/reset")
    return text

def patch_translations(root: Path, apply: bool) -> list[str]:
    if not PROJECT_LOCALES_DIR.exists():
        fail(f"Missing locales directory: {PROJECT_LOCALES_DIR}")

    locale_files = sorted(PROJECT_LOCALES_DIR.glob("*.json"))
    locale_files = [path for path in locale_files if path.name != "TEMPLATE.json"]
    if not locale_files:
        fail(f"No locale JSON files found in: {PROJECT_LOCALES_DIR}")

    fallback_path = PROJECT_LOCALES_DIR / f"{PROJECT_CONFIG['fallback_locale']}.json"
    fallback_values = load_json_object(fallback_path, "fallback locale")
    required_keys = {key for key, value in fallback_values.items() if isinstance(value, str)}

    changed: list[str] = []
    for source_path in locale_files:
        locale = source_path.stem
        values = load_json_object(source_path, f"locale {locale}")
        string_values = {key: value for key, value in values.items() if isinstance(value, str)}
        missing = sorted(required_keys - set(string_values))
        if missing:
            fail(f"{source_path.name}: missing translation keys: {', '.join(missing)}")

        target = root / "frontend/app/lang/messages" / source_path.name
        if not target.exists():
            print(f"Skipping locale {locale}: Mealie does not ship {target.name}")
            continue

        data = json.loads(target.read_text(encoding="utf-8"))
        meal_plan = data.get("meal-plan")
        if not isinstance(meal_plan, dict):
            fail(f"{target.name}: missing meal-plan translation object")

        if any(meal_plan.get(key) != value for key, value in string_values.items()):
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
    }

    for rel in transforms:
        if not (root / rel).exists():
            fail(f"Missing expected Mealie source file: {rel}")

    changes = []
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

    print("Mealie Weekly Leftovers patch applied successfully." if apply else "Mealie Weekly Leftovers compatibility check passed.")
    if changes:
        print("Changed files:" if apply else "Files that would change:")
        for item in sorted(set(changes)):
            print(f"  - {item}")
    else:
        print("Patch is already applied; no changes required.")

def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Mealie Meal Planner with Weekly Leftovers support.")
    parser.add_argument("--root", required=True, type=Path, help="Extracted Mealie source tree")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Project configuration JSON")
    parser.add_argument("--locales", type=Path, default=DEFAULT_LOCALES_DIR, help="Directory containing locale JSON files")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    try:
        configure_project(args.config.resolve(), args.locales.resolve())
        run(args.root.resolve(), args.apply)
    except Exception as exc:
        print(f"Weekly Leftovers patch FAILED: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
