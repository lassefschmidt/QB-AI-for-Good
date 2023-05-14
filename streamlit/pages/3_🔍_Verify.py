import pandas as pd
import os
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
import reverse_geocoder as rg
import pycountry
import streamlit as st
from streamlit_folium import st_folium
import datetime
import branca
import torch
from sklearn.metrics import accuracy_score, roc_auc_score
from PIL import Image


# Layout
st.set_page_config(layout="wide")
margin = 0
padding = 2

# Layout
st.markdown(f"""
    <style>
        .block-container{{
            padding-top: 0rem;
            padding-bottom : 0rem;
            padding-left: {padding}rem;
            padding-right: {padding}rem;
            margin: {margin}rem;
        }}

        .css-1oe5cao{{
            padding-top: 2rem;
        }}
    </style>""",
    unsafe_allow_html=True,
)

# Get the base path of the Streamlit app
base_path = os.path.abspath(__file__)

#parent directory to get to the map folder
parent_path = os.path.dirname(os.path.dirname(base_path))

# Specify the relative path to the Shapefile within the subfolder
file_path = parent_path + "/map/map.shp"

# read map file
gdf = gpd.read_file(file_path) 

# Add datetime
gdf['datetime'] =  pd.to_datetime(gdf['date'], format= "%Y%m%d")

with st.sidebar:
    st.header('Enter your filters:')
    plumes = st.selectbox('Display', ('All','Only Plumes'))
    period = st.date_input( "Period of Interest", (datetime.date(2023, 1, 1),datetime.date(2023, 12, 31) ))
    sectors = st.multiselect('Sectors', sorted(list(gdf['sector'].unique())))
    companies = st.multiselect('Companies', sorted(list(gdf['company'].unique())))
    countries = st.multiselect('Countries', sorted(list(gdf['country'].unique())))

#Apply filters
gdf_filtered = gdf.copy()

# Filter on the display
if plumes=='Only Plumes':
    gdf_filtered = gdf_filtered[gdf_filtered['plume']=='yes']

    # Filter on the sectors
    if sectors !=[]:
        gdf_filtered = gdf_filtered[gdf_filtered['sector'].isin(sectors)]

    # Filter on the companies
    if companies !=[]:
        gdf_filtered = gdf_filtered[gdf_filtered['company'].isin(companies)]

    # Filter on the countries
    if countries !=[]:
        gdf_filtered = gdf_filtered[gdf_filtered['country'].isin(countries)]

    # Filter on date
    if len(period)<2:
        gdf_filtered = gdf_filtered[(gdf_filtered["datetime"] == pd.Timestamp(period[0]))]
    else:
        gdf_filtered = gdf_filtered[(gdf_filtered["datetime"] >= pd.Timestamp(period[0])) & (gdf_filtered["datetime"] <= pd.Timestamp(period[1]))]
    gdf_filtered["datetime"] = gdf_filtered["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")

else:
    # Filter on the sectors
    if sectors !=[]:
        gdf_filtered = gdf_filtered[gdf_filtered['sector'].isin(sectors)]

    # Filter on the companies
    if companies !=[]:
        gdf_filtered = gdf_filtered[gdf_filtered['company'].isin(companies)]

    # Filter on the countries
    if countries !=[]:
        gdf_filtered = gdf_filtered[gdf_filtered['country'].isin(countries)]

    # Filter on date
    if len(period)<2:
        gdf_filtered = gdf_filtered[(gdf_filtered["datetime"] == pd.Timestamp(period[0]))]
    else:
        gdf_filtered = gdf_filtered[(gdf_filtered["datetime"] >= pd.Timestamp(period[0])) & (gdf_filtered["datetime"] <= pd.Timestamp(period[1]))]
    gdf_filtered["datetime"] = gdf_filtered["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")

#Cache data
@st.cache_data
def convert_df(df):
    # IMPORTANT: Cache the conversion to prevent computation on every rerun
    return df.to_csv().encode('utf-8')

# Download data as csv
csv = convert_df(pd.DataFrame(gdf_filtered))
with st.sidebar:
    st.download_button(
        label="Download data as CSV",
        data=csv,
        file_name='large_df.csv',
        mime='text/csv',
    )

# Write dataframe to map
if gdf_filtered.shape[0]<1:
    st.header('No Result found for this query')
else:
    #Filter on the columns to be displayed
    gdf_filtered = gdf_filtered.rename(columns={'Concentrat':'Concentration Uncertainty (ppm m)',
                                                 'Max Plume':'Max Plume Concentration (ppm m)',
                                                 'Emission': 'Estimated Emission rate (CH4 tonnes/hour)',
                                                 'Duration':'Estimated Duration (hours)',
                                                 'Total' : 'Total Emissions (kt CH4)' ,
                                                 'CO2eq': 'Total Emissions (kt CO2eq)' })
    display_columns = ['id_coord',
                        'plume',
                        'city',
                        'country',
                        'company',
                        'sector',
                        'Concentration Uncertainty (ppm m)',
                        'Max Plume Concentration (ppm m)',
                        'datetime',
                        'Estimated Emission rate (CH4 tonnes/hour)',
                        'Estimated Duration (hours)',
                        'Total Emissions (kt CH4)',
                        'Total Emissions (kt CO2eq)']

    # Filter on display columns
    gdf_filtered = gdf_filtered[display_columns]
    
    ### Prediction from model 
    # Title and Side Bar for filters
    st.title("Follow-up of open leaks")

    # Boolean to resize the dataframe, stored as a session state variable
    st.checkbox("Use container width", value=False, key="use_container_width")

    # Follow-up dataframe
    display_image = st.session_state.use_container_width

    # columns
    col1, col2 = st.columns([6,1])

    with col1:
        st.dataframe(pd.DataFrame(gdf_filtered),height = 500 , use_container_width=True)

    with col2:
        st.write('Original image')
        original_filename = parent_path+'/map/images/plume/20230102_methane_mixing_ratio_id_1465.tif'
        original_image = Image.open(original_filename)
        original_image = original_image.convert("RGB")
        st.image(original_image,use_column_width=True) 
        st.divider()
        st.write('Heatmap')
        gradcam_filename = parent_path+'/map/images/plume/20230102_methane_mixing_ratio_id_1465.tif'
        gradcam_image = Image.open(original_filename)
        gradcam_image = gradcam_image.convert("RGB")
        st.image(gradcam_image,use_column_width=True)        

    # Title and Side Bar for filters
    st.title("Add new entries")
    # Add New entry for prediction
    zipfile = st.file_uploader('Upload satelite images to predict potential plumes:', type=None, accept_multiple_files=False, help='The zip file must contain no subfolders. The metadata must contain complete and accurate information.')

    def predict(dataloader, model, criterion, device,test_set=True):
        model.eval()
        losses = []
        idxs = torch.Tensor([])
        lbls = torch.Tensor([])
        preds = torch.Tensor([])
        
        if test_set:
            for batch_idx, batch in enumerate(dataloader):
                # decompose batch and move to device
                idx_batch, img_batch, lbl_batch = batch
                idxs = torch.cat((idxs, idx_batch))
                lbls = torch.cat((lbls, lbl_batch))
                lbl_batch = lbl_batch.type(torch.float32) # cast to long to be able to compute loss
                img_batch, lbl_batch = img_batch.to(device), lbl_batch.to(device)
                
                # forward
                logits = model(img_batch).float().squeeze(1)
                loss = criterion(logits.to(device), lbl_batch)
                
                # logging
                losses.append(loss.item())
                preds = torch.cat((preds, torch.sigmoid(logits).cpu()))
        else:
            for batch_idx, batch in enumerate(dataloader):
                # decompose batch and move to device
                idx_batch, img_batch, lbl_batch = batch
                idxs = torch.cat((idxs, idx_batch))
                lbls = torch.cat((lbls, lbl_batch))
                lbl_batch = lbl_batch.type(torch.float32) # cast to long to be able to compute loss
                img_batch, lbl_batch = img_batch.to(device), lbl_batch.to(device)
                
                # forward
                logits = model(img_batch).float().squeeze(1)
                loss = criterion(logits.to(device), lbl_batch)
                
                # logging
                losses.append(loss.item())
                preds = torch.cat((preds, torch.sigmoid(logits).cpu()))
                
            # compute stats
            acc = accuracy_score(lbls.detach().numpy(), (preds.detach().numpy() > 0.5))
            auc = roc_auc_score(lbls.detach().numpy(), preds.detach().numpy())
            loss_mean = np.mean(losses)
            
            return acc, auc, loss_mean

