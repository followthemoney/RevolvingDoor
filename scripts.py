import pandas as pd
import json
from pandas import json_normalize
import PyPDF2
import spacy
from tqdm.notebook import tqdm

def import_MEP(path):
    df_MEP = pd.read_excel(path) # Dataset from the 
    #Set first row as header
    df_MEP.columns = df_MEP.iloc[0]
    df_MEP = df_MEP.drop(0)
    df_MEP['fullname'] = df_MEP['NOM'].str.lower()
    return df_MEP

def import_accredited(json_file):
    with open(json_file) as inputfile:
        my_json = json.load(inputfile) #Loads a list
    df_accredited = json_normalize(my_json)
    df_accredited = pd.DataFrame.from_dict(my_json['resultList']['accreditedPerson'])
    df_accredited['fullname'] = (df_accredited['lastName']+' ' +df_accredited['firstName']).str.lower()
    return df_accredited

def import_ECB(path):
    # creating a pdf reader object
    reader = PyPDF2.PdfReader(path)
    NER = spacy.load("en_core_web_trf")
    peoples = []
    for page in tqdm(reader.pages):
        text1= NER(" ".join(page.extract_text().split()))#remove double spaces and rejoin text
        for word in text1.ents:
            #print(word.text,word.label_)
            if word.label_ == 'PERSON':
                peoples.append(word.text)
    return peoples

def create_variation(peoples):
    name_variations = []
    # Generate variations depending on the order (last + fist name / first + last name)
    for name in tqdm(peoples):
        parts = name.split()
        if len(parts) > 1:
            last_first = f"{parts[-1]} {' '.join(parts[:-1])}".replace('- ', '-').lower()
            first_last = f"{' '.join(parts)}".replace('- ', '-').lower()
            name_variations.append(last_first)
            name_variations.append(first_last)
        else:
            name_variations.append(name)

    return name_variations