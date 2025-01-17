#!/usr/bin/env python
# coding: utf-8

import os
import math
import sys
import pathlib
import numpy as np
import pandas as pd
from tqdm.auto import tqdm
from IPython.display import clear_output

import warnings
import lifelines
from lifelines.utils import CensoringType
from lifelines.utils import concordance_index

from lifelines import CoxPHFitter
from lifelines.exceptions import ConvergenceError, ConvergenceWarning
from formulaic.errors import FactorEvaluationError
import zstandard
import pickle
import yaml
import ray

from datetime import date

def get_score_defs():

    #with open(r'/sc-projects/sc-proj-ukb-cvd/results/projects/22_retina_phewas_220603_fullrun/data/score_definitions.yaml') as file:
    
    score_defs = {
        "AgeSex": [
            "age", 
            "sex_Male"],
        "SCORE2": [
            "age", 
            "sex_Male",
            "smoking_status_Current", # current smoker
            "smoking_status_Former",
            "smoking_status_Never",
            "systolic_blood_pressure",
            "cholesterol",
            "hdl_cholesterol",], 

        "ASCVD": [
            "age", 
            "sex_Male",
            #"ethnic_background",
            "smoking_status_Current", # current smoker
            "smoking_status_Former",
            "smoking_status_Never",
            "diabetes", # diabetes
            #"antihypertensives", 
            "systolic_blood_pressure",
            "cholesterol",
            "hdl_cholesterol",] 
        }
    
    return score_defs

def get_features(endpoint, score_defs, models):
    features = {
        model: {
             "Age+Sex": score_defs["AgeSex"],
             "Retina": [endpoint],
             "SCORE2": score_defs["SCORE2"],
             "ASCVD": score_defs["ASCVD"],
#             "QRISK3": score_defs["QRISK3"],
            "Age+Sex+Retina": score_defs["AgeSex"] + [endpoint],
            "SCORE2+Retina": score_defs["SCORE2"] + [endpoint],
            "ASCVD+Retina": score_defs["ASCVD"] + [endpoint],
#            "QRISK3+Retina": score_defs["QRISK3"] + [endpoint],
            }
    for model in models}
    return features

#def get_train_data(in_path, partition, models, data_outcomes, mapping):
def get_train_data(in_path, partition, models, data_outcomes):
 #   train_data = {}
    
  #  for model in models:
#        train = pd.read_feather(f"{in_path}/{model}/{partition}/train.feather")\
#                .set_index("eid").merge(data_outcomes, left_index=True, right_index=True, how="left")
#        valid = pd.read_feather(f"{in_path}/{model}/{partition}/valid.feather")\
#                .set_index("eid").merge(data_outcomes, left_index=True, right_index=True, how="left")
#        combined = pd.concat([train, valid], axis=0)
        
#    train_data[model] = combined
    
    train_data = {
     model: pd.read_feather(f"{in_path}/{model}/{partition}/train.feather")\
     .set_index("eid").merge(data_outcomes, left_index=True, right_index=True, how="left")#.replace(mapping)
     for model in models}
        
    return train_data

def fit_cox(data_fit, feature_set, covariates, endpoint, penalizer):
    #print(data_fit, feature_set, covariates, endpoint, penalizer, step_size)
    
    # drop columns with only one value -> doesnt make sense as predictor
    data_fit = data_fit.select_dtypes(include=['int', 'float']).loc[:, data_fit.select_dtypes(include=['int', 'float']).nunique() > 1]
    
    # initialize and fit model
    cph = CoxPHFitter(penalizer=penalizer)
    cph.fit(data_fit, f"{endpoint}_time", f"{endpoint}_event")
    return cph

def save_pickle(data, data_path):
    with open(data_path, "wb") as fh:
        cctx = zstandard.ZstdCompressor()
        with cctx.stream_writer(fh) as compressor:
            compressor.write(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
            
def load_pickle(fp):
    with open(fp, "rb") as fh:
        dctx = zstandard.ZstdDecompressor()
        with dctx.stream_reader(fh) as decompressor:
            data = pickle.loads(decompressor.read())
    return data

def clean_covariates(endpoint, covariates):
    if endpoint=="phecode_181": # Autoimmune disease
        covariates = [c for c in covariates if c!="systemic_lupus_erythematosus"]
    if endpoint=="phecode_202": # Diabetes
        covariates = [c for c in covariates if c not in ['diabetes1', 'diabetes2', 'diabetes']]
    if endpoint=="phecode_202-1": # Diabetes 1
        covariates = [c for c in covariates if c!="diabetes1"]
    if endpoint=="phecode_202-2": # Diabetes 1
        covariates = [c for c in covariates if c!="diabetes2"]
    if endpoint=="phecode_286": # Mood [affective] disorders
        covariates = [c for c in covariates if c not in ['bipolar_disorder', 'major_depressive_disorder']]
    if endpoint=="phecode_286-1": # Bipolar disorder
        covariates = [c for c in covariates if c not in ['bipolar_disorder']]
    if endpoint=="phecode_286-2": # Major depressive disorder
        covariates = [c for c in covariates if c not in ['major_depressive_disorder']]
    if endpoint=="phecode_287": # psychotic disorders
        covariates = [c for c in covariates if c not in ['schizophrenia']]
    if endpoint=="phecode_287-1": # schizophrenia
        covariates = [c for c in covariates if c not in ['schizophrenia']]
    if endpoint=="phecode_331": # headache
        covariates = [c for c in covariates if c!="migraine"]
    if endpoint=="phecode_331-6": # headache
        covariates = [c for c in covariates if c!="migraine"]
    if endpoint=="phecode_416": # atrial fibrillation
        covariates = [c for c in covariates if c not in ['atrial_fibrillation']]
    if endpoint=="phecode_416-2": # atrial fibrillation and flutter
        covariates = [c for c in covariates if c not in ['atrial_fibrillation']]
    if endpoint=="phecode_416-21": # atrial fibrillation
        covariates = [c for c in covariates if c not in ['atrial_fibrillation']]
    if endpoint=="phecode_584": # Renal failure
        covariates = [c for c in covariates if c not in ['renal_failure']]
    if endpoint=="phecode_605": # Male sexual dysfuction
        covariates = [c for c in covariates if c not in ['sex_Male', 'male_erectile_dysfunction']]
    if endpoint=="phecode_605-1": # Male sexual dysfuction
        covariates = [c for c in covariates if c not in ['sex_Male', 'male_erectile_dysfunction']]
    if endpoint=="phecode_700": # Diffuse diseases of connective tissue
        covariates = [c for c in covariates if c not in ['systemic_lupus_erythematosus']]
    if endpoint=="phecode_700-1": # Lupus
        covariates = [c for c in covariates if c not in ['systemic_lupus_erythematosus']]
    if endpoint=="phecode_700-11": # Systemic lupus erythematosus [SLE]	
        covariates = [c for c in covariates if c not in ['systemic_lupus_erythematosus']]
    if endpoint=="phecode_705": # Rheumatoid arthritis and other inflammatory
        covariates = [c for c in covariates if c not in ['rheumatoid_arthritis']]
    if endpoint=="phecode_705-1": # Rheumatoid arthritis and other inflammatory
        covariates = [c for c in covariates if c not in ['rheumatoid_arthritis']]
    # added by lukas
    if endpoint=='phecode_620':
        covariates = [c for c in covariates if c not in ['sex_Male', 'male_erectile_dysfunction']]
    if endpoint=='phecode_627':
        covariates = [c for c in covariates if c not in ['sex_Male', 'male_erectile_dysfunction']]
    if endpoint=='phecode_627-4':
        covariates = [c for c in covariates if c not in ['sex_Male', 'male_erectile_dysfunction']]
    return covariates

def load_data(partition):
    base_path = "/home/jakobs"

    project_path = f"{base_path}/data"

    experiment = '231117'
    experiment_path = f"{project_path}/{experiment}"
    pathlib.Path(experiment_path).mkdir(parents=True, exist_ok=True)

    partitions = [i for i in range(10)]
    
    today = experiment
    # today = None
    
    #### ^^^^ ####
    
    in_path = pathlib.Path(f"{experiment_path}/coxph/input")
    in_path.mkdir(parents=True, exist_ok=True)

    model_path = f"{experiment_path}/coxph/models"
    pathlib.Path(model_path).mkdir(parents=True, exist_ok=True)

    data_outcomes = pd.read_feather(f"{base_path}/data/data_outcomes_wide_230320.feather").set_index("eid")
    
    #endpoints_md = pd.read_csv(f"{experiment_path}/endpoints.csv")
    #endpoints = sorted(endpoints_md.endpoint.to_list())
    phecode = pd.read_csv(f"{base_path}/mapping/phecode_strings_V2.csv")[["phecode_string", "sex"]]
    endpoint_defs = pd.read_feather(f"{base_path}/data/endpoints_epic_md.feather").merge(phecode, how="left", on="phecode_string").set_index("endpoint")#
    endpoint_defs.iloc[0, endpoint_defs.columns.get_loc('sex')] = "Both"
    endpoints = endpoint_defs.index.to_list()
    
    eligible_eids = pd.read_feather(f"{experiment_path}/eligible_eids_{today}.feather")
    eids_dict = eligible_eids.set_index("endpoint")["eid_list"].to_dict()

    models = ['RetinaUKB', 
              #'ImageTraining_[]_ConvNeXt_MLPHead_predictions_cropratio0.5', 
              #'ImageTraining_[]_ConvNeXt_MLPHead_predictions_cropratio0.8'
             ]
    
    #mapping = {"sex_f31_0_0": {"Female":0, "Male":1}}
    
    score_defs = get_score_defs()

    data_partition = get_train_data(in_path, partition, models, data_outcomes)
    #data_partition = get_train_data(in_path, partition, models, data_outcomes, mapping)

    return eids_dict, score_defs, endpoint_defs, endpoints, models, model_path, experiment_path, data_partition

@ray.remote(num_cpus=1)
def fit_endpoint(data_partition, eids_dict, score_defs, endpoint_defs, endpoint, partition, models, model_path, experiment_path):
    eids_incl = eids_dict[endpoint].tolist()
    features = get_features(endpoint, score_defs, models)
    eligibility = endpoint_defs.loc[endpoint]["sex"]
    for model in models:
        data_model = data_partition[model]
        for feature_set, covariates in features[model].items():
            cph_path = f"{model_path}/{endpoint}_{feature_set}_{model}_{partition}.p"
            if os.path.isfile(cph_path):
                try:
                    cph = load_pickle(cph_path)
                    success = True
                except:
                    success = False
                    pass
            if not os.path.isfile(cph_path) or success==False:
                if (eligibility != "Both") and ("sex_Male" in covariates): # and ("sex_Male" in covariates) / and ("sex_f31_0_0" in covariates)
                    covariates = [c for c in covariates if c!="sex_Male"] # if c!="sex_Male" / if c!="sex_f31_0_0"
                
                # make sure cox models can fit ("LinAlgError: Matrix is singular")
                covariates = clean_covariates(endpoint, covariates)

                data_endpoint = data_model[covariates + [f"{endpoint}_event", f"{endpoint}_time"]].astype(np.float32)
                data_endpoint = data_endpoint[data_endpoint.index.isin(eids_incl)]
                cph = None
                for penalizer in [0, 0.0125, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2]:
                    with warnings.catch_warnings(record=True) as w:
                        # Treat warnings as errors
                        warnings.simplefilter("error", ConvergenceWarning)
                        try:
                            cph = fit_cox(data_endpoint, feature_set, covariates, endpoint, penalizer=penalizer)
                            save_pickle(cph, cph_path)
                        except (ConvergenceWarning, ConvergenceError):
                            pass
                    if cph is None:
                        if penalizer<0.2:
                            pass
                        else:
                            print("ConvergenceError", model, endpoint, feature_set, partition, f"is not converging, saved file")
                            save_pickle(data_setting, f"{experiment_path}/coxph/errordata_{endpoint}_{feature_set}_{partition}.p")
                    if cph is not None:
                        break
                        
def main(args):

    # prepare env variables for ray
    os.environ['MKL_NUM_THREADS'] = "1"
    os.environ['NUMEXPR_NUM_THREADS'] = "1"
    os.environ['OMP_NUM_THREADS'] = "1"

    # prepare data
    partition = int(args[1])
    eids_dict, score_defs, endpoint_defs, endpoints, models, model_path, experiment_path, data_partition = load_data(partition)

    # setup ray and put files in plasma storage
    #ray.init(num_cpus=24) # crashes if num_cpus > 16, why not more possible?
    ray.init(address="auto")
    ray_eids = ray.put(eids_dict)
    ray_score_defs = ray.put(score_defs)
    ray_endpoint_defs = ray.put(endpoint_defs)
    ray_partition = ray.put(data_partition)
    
    # fit cox models via ray
    progress = []
    for endpoint in endpoints:
        progress.append(fit_endpoint.remote(ray_partition, ray_eids, ray_score_defs, ray_endpoint_defs, endpoint, partition, models, model_path, experiment_path))
    [ray.get(s) for s in tqdm(progress)]
    
    ray.shutdown()

if __name__ == "__main__":
    main(sys.argv)