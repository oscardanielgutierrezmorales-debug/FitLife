export function MealCard({ meal }) { return <article className="meal"><strong>{meal.meal_type}</strong><span>{meal.name}</span><small>{meal.portions} · {meal.calories} kcal · proteína {meal.macros.protein_g} g</small><p>{meal.instructions}</p></article>; }

