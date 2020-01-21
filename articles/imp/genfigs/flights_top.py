from support import *

figsize = (3.5, 3.0)
use_oob=False
metric = mean_absolute_error
n = 25_000
model='RF' # ('RF','SVM','GBM')

X, y, _ = load_flights(n=n)

R, Rstd, spear_I, pca_I, ols_I, shap_ols_I, rf_I, perm_I, our_I = \
    compare_top_features(X, y, n_shap=300,
                         catcolnames={'AIRLINE',
                                      'ORIGIN_AIRPORT',
                                      'DESTINATION_AIRPORT',
                                      'FLIGHT_NUMBER',
                                      'DAY_OF_WEEK'},
                         kfolds=1,
                         model=model,
                         metric=mean_absolute_error,
                         stratpd_min_samples_leaf=5,
                         stratpd_cat_min_samples_leaf=2,
                         use_oob=use_oob,
                         imp_n_trials=3,
                         top_features_range=(1, 8),
                         drop=['Spearman','PCA'])

plot_importances(our_I.iloc[0:8], imp_range=(0, .4), width=4.1,
                 title="Flight delay StratImpact importances")
plt.tight_layout()
plt.savefig("../images/flights-features.pdf", bbox_inches="tight", pad_inches=0)
plt.show()

plot_importances(rf_I.iloc[0:8], imp_range=(0, .4), width=4.1,
                 title="Flight delay RF SHAP importances")
plt.tight_layout()
plt.savefig("../images/flights-features-shap-rf.pdf", bbox_inches="tight", pad_inches=0)
plt.show()

print(R)

R = R.reset_index(drop=True)
R.reset_index().to_feather("/tmp/flights.feather")

plot_topk(R, k=8, title=f"{model} Flight arrival delay",
          ylabel="20% 5-fold CV MAE (mins)",
          title_fontsize=14,
          label_fontsize=14,
          ticklabel_fontsize=10,
          figsize=figsize)
plt.tight_layout()
plt.savefig(f"../images/flights-topk-{model}.pdf", bbox_inches="tight", pad_inches=0)
plt.show()