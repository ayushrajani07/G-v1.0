# ML Arm Quick Start

This is a lightweight, plug-and-play ML scaffolding designed to let you drop in
new models with minimal boilerplate.

## Concepts

- ModelPlugin protocol: `fit(X, y, **params)`, `predict(X)`, `save(path)`, `load(path)`
- Registry: `register_model(name, factory)` + `get_model(name)` + `list_models()`
- Config: JSON file with `model_name`, `dataset_path`, `features`, `target_column`, `params`, and artifact settings
- Datasets: CSV loader to produce NumPy `X`, `y`

## Files

- `src/ml_arm/interfaces.py` — ModelPlugin protocol
- `src/ml_arm/registry.py` — registry utilities
- `src/ml_arm/config.py` — MLConfig dataclass + JSON loader
- `src/ml_arm/datasets.py` — CSV loader (NumPy)
- `src/ml_arm/utils.py` — `set_global_seed(seed)`
- `src/ml_arm/plugins/baseline_linear.py` — NumPy least-squares baseline (optional Torch)
- `src/ml_arm/plugins/torch_mlp.py` — Torch MLP regressor (GPU optional)
- `scripts/ml/train_model.py` — Train from config, save artifact
- `scripts/ml/run_infer.py` — Load artifact, print sample prediction
- `scripts/ml/evaluate.py` — Evaluate saved artifact (MSE on holdout split)
- `scripts/ml/list_models.py` — Show registered model names
- `configs/ml/example_linear.json` — Baseline sample config
- `configs/ml/example_mlp.json` — Torch MLP sample config

## Try it

- List models

```bash
python scripts/ml/list_models.py
```

- Train baseline

```bash
python scripts/ml/train_model.py --config configs/ml/example_linear.json --seed 123
```

- Infer

```bash
python scripts/ml/run_infer.py --config configs/ml/example_linear.json
```

- Train Torch MLP (GPU optional)

```bash
python scripts/ml/train_model.py --config configs/ml/example_mlp.json --seed 123
```

- Evaluate

```bash
python scripts/ml/evaluate.py --config configs/ml/example_mlp.json --seed 123
```

## Adding a new model

1. Create `src/ml_arm/plugins/my_model.py`
2. Implement ModelPlugin methods
3. Register: `register_model(MyModel.name, lambda: MyModel())`
4. Add a config JSON referencing `model_name: "my_model"`
5. Use the existing train/evaluate scripts

## Notes

- Torch MLP loader defaults to CPU for safe inference; switch to CUDA manually if desired
- Use `--seed` to make runs reproducible (NumPy and Torch seeded)
- For larger datasets, consider adding a Parquet dataset loader and minibatched evaluation

## Using "normal" CSVs

Most real-world CSVs have quirks: different delimiters, blank cells, or strings that should be treated as missing.
Add `dataset_opts` in your config to guide parsing. The loader will use pandas if available, otherwise it falls back to the built-in CSV reader.

Supported options:

- `delimiter` (default ",")
- `na_values` (default `["", "NA", "NaN", "null", "None"]`)
- `dropna` (default `true`) — rows with missing feature/target are dropped

Example:

```json
{
	"model_name": "baseline_linear",
	"dataset_path": "data/ml/mydata.csv",
	"target_column": "y",
	"features": ["x1", "x2", "x3"],
	"dataset_opts": {
		"delimiter": ";",
		"na_values": ["", "NA", "-"],
		"dropna": true
	}
}
```

If pandas is installed, we use `pd.read_csv(..., sep=delimiter, na_values=..., keep_default_na=True)` and coerce
columns to numeric with `errors="coerce"`, dropping rows with missing values for the selected columns.

## Loading a directory of CSVs

Point `dataset_path` to a directory and add `dataset_opts` for file discovery. The loader will
concatenate all matching CSVs. Example:

```json
{
	"model_name": "baseline_linear",
	"dataset_path": "data/g6_data/NIFTY/this_week/0",
	"target_column": "y",
	"features": ["x1", "x2"],
	"dataset_opts": {
		"pattern": "*.csv",
		"recursive": true,
		"delimiter": ",",
		"na_values": ["", "NA", "NaN", "null", "None"],
		"dropna": true
	}
}
```

If pandas is available, we load with `pd.read_csv` and `pd.concat` (fast and robust). Otherwise we
fall back to a CSV reader and basic NA handling, then concatenate NumPy arrays.
