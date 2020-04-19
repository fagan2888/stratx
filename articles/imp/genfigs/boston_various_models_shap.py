
from stratx.featimp import importances, plot_importances
from support import shap_importances, models

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.datasets import load_boston
import tempfile
from sklearn.linear_model import LinearRegression, Lasso, LogisticRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.utils import resample
from sklearn.model_selection import train_test_split
from timeit import default_timer as timer
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GridSearchCV

import xgboost as xgb
from sklearn import svm

np.random.seed(44) # choose a seed that demonstrates diff RF/GBM importances

boston = load_boston()
X = pd.DataFrame(boston.data, columns=boston.feature_names)
y = pd.Series(boston.target)

n = X.shape[0]
n_shap=len(X)

fig, axes = plt.subplots(1,4,figsize=(10,2.5))

lm = LinearRegression()
X_ = StandardScaler().fit_transform(X)
X_ = pd.DataFrame(X_, columns=X.columns)
lm.fit(X_, y)
lm_score = lm.score(X_,y)
print("OLS", lm_score, mean_absolute_error(y, lm.predict(X_)))
ols_shap_I = shap_importances(lm, X_, X_, n_shap=n_shap)  # fast enough so use all data
print(ols_shap_I)

"""
Uncomment to compute variance of RF SHAP
n_rf_trials = 15
all_rf_I = np.empty(shape=(n_rf_trials,X.shape[1]))
for i in range(n_rf_trials):
    rf = RandomForestRegressor(n_estimators=20, min_samples_leaf=5, oob_score=True)
    rf.fit(X, y)
    rf_I = shap_importances(rf, X, X, n_shap, sort=False)
    all_rf_I[i,:] = rf_I['Importance'].values
    rf_score = rf.score(X, y)
    print("RF", rf_score, rf.oob_score_, mean_absolute_error(y, rf.predict(X)))

rf_I = pd.DataFrame(data={'Feature': X.columns,
                           'Importance': np.mean(all_rf_I, axis=0),
                           'Sigma': np.std(all_rf_I, axis=0)})
rf_I = rf_I.set_index('Feature')
rf_I = rf_I.sort_values('Importance', ascending=False)
rf_I.reset_index().to_feather("/tmp/t.feather")
# print(rf_I)
"""

tuned_params = models[("boston", "RF")]
rf = RandomForestRegressor(**tuned_params, oob_score=True, n_jobs=-1)
rf.fit(X, y)
rf_I = shap_importances(rf, X, X, n_shap)
rf_score = rf.score(X, y)
print("RF", rf_score, rf.oob_score_, mean_absolute_error(y, rf.predict(X)))

tuned_params = models[("boston", "GBM")]
b = xgb.XGBRegressor(**tuned_params, n_jobs=-1)
b.fit(X, y)
xgb_score = b.score(X, y)
print("XGB training R^2", xgb_score)
m_I = shap_importances(b, X, X, n_shap)
b_score = b.score(X, y)
print("XGBRegressor", b_score, mean_absolute_error(y, b.predict(X)))

tuned_params = models[("boston", "SVM")]
s = svm.SVR(**tuned_params)
X_ = StandardScaler().fit_transform(X)
X_ = pd.DataFrame(X_, columns=X.columns)
s.fit(X_, y)
svm_score = s.score(X_, y)
print("svm_score", svm_score)
svm_shap_I = shap_importances(s, X_, X_, n_shap=n_shap)
"""
Takes 13 minutes for all records
100%|██████████| 506/506 [13:30<00:00,  1.60s/it]
SHAP time for 506 test records using SVR = 810.1s
"""

plot_importances(ols_shap_I.iloc[:8], ax=axes[0], imp_range=(0,.4), width=2.5, xlabel='(a)')
axes[0].set_title(f"OLS train $R^2$={lm_score:.2f}")
plot_importances(rf_I.iloc[:8], ax=axes[1], imp_range=(0,.4), width=2.5, xlabel='(b)')
axes[1].set_title(f"RF train $R^2$={rf_score:.2f}")
plot_importances(m_I.iloc[:8], ax=axes[2], imp_range=(0,.4), width=2.5, xlabel='(c)')
axes[2].set_title(f"XGBoost train $R^2$={b_score:.2f}")
plot_importances(svm_shap_I.iloc[:8], ax=axes[3], imp_range=(0,.4), width=2.5, xlabel='(d)')
axes[3].set_title(f"SVM train $R^2$={svm_score:.2f}")

plt.suptitle(f"SHAP importances for Boston dataset: {n:,d} records, {n_shap} SHAP test records")
plt.tight_layout()
plt.savefig("../images/diff-models.pdf",
            bbox_inches="tight", pad_inches=0)
plt.show()

