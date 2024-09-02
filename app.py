import streamlit as st
import pandas as pd
import csv
from currency_converter import ECB_URL, CurrencyConverter
from datetime import date
from io import StringIO
import urllib.request
from typing import Tuple

_ = """
Funktionen dieser App:
- Parsen der Transaktionen aus den Reports
- Tagesgenaue Umrechnung des Transaktions-GuV von USD in EUR
- Aufteilung des GuV in Steuertöpfe (Gewinne/Verluste aus Termingeschäften/Stillhaltergeschäften)


Unterstützt Reports als CSV-Dateien von IBKR und Tasty.

ACHTUNG:
========
GuV aus Geschäften mit Aktien, Indizes, Futures und Devisen 
sowie Dividenden und Zinsen werden nicht berücksichtigt.
"""

# FUNCTIONS
def download_fx_data() -> None:
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
    urllib.request.urlretrieve(url, "eurofxref-hist.zip")

def init_currencyconverter():
    download_fx_data()
    c = CurrencyConverter(ECB_URL, fallback_on_missing_rate=True)
    return c

def process_ibkr_statement(csvfile) -> Tuple[pd.DataFrame, float, float]:
    data = csv.reader(csvfile, delimiter=",", quotechar="\"")
    transactions = []
    for row in data:
        if row[0] == "Transaktionen":
            transactions.append(row)    

    # transactions to df; skip header row
    df = pd.DataFrame.from_records(transactions[1:], columns=transactions[0])

    # select only options trades
    df_clean = df[(df.Header == "Data") & (df.Vermögenswertkategorie == "Aktien- und Indexoptionen")]
    df_clean["Datum/Zeit"] = pd.to_datetime(df_clean["Datum/Zeit"], format="%Y-%m-%d, %H:%M:%S")

    for col in ["Menge", "Basis", "Realisierter G&V"]:
        df_clean[col] = df_clean[col].astype(float)

    # assign trade types
    df_clean.loc[(df_clean["Menge"] > 0) & (df_clean["Code"].str.contains("O")), "Typ"] = "BTO"   # open long
    df_clean.loc[(df_clean["Menge"] < 0) & (df_clean["Code"].str.contains("C")), "Typ"] = "STC"   # close long
    df_clean.loc[(df_clean["Menge"] < 0) & (df_clean["Code"].str.contains("O")), "Typ"] = "STO"   # open short
    df_clean.loc[(df_clean["Menge"] > 0) & (df_clean["Code"].str.contains("C")), "Typ"] = "BTC"   # close short    

    # Steuerliche Zuordnung
    # Vereinnahmung bzw. Glattstellung von Stillhaltergeschäften müssen separat betrachtet werden!
    df_clean.loc[df_clean["Typ"] == "STC", "GuV Termingeschäfte"] = df_clean["Realisierter G&V"]
    df_clean.loc[df_clean["Typ"] == "STO", "GuV Stillhaltergeschäfte"] = -df_clean["Basis"]
    df_clean.loc[df_clean["Typ"] == "BTC", "GuV Stillhaltergeschäfte"] = df_clean["Realisierter G&V"] - df_clean["Basis"]
    
    c = init_currencyconverter()

    df_clean["GuV Termingeschäfte EUR"] = df_clean.apply(
        lambda x: c.convert(
            x["GuV Termingeschäfte"], 
            'USD', 'EUR', 
            date=x["Datum/Zeit"].date()), 
        axis=1)

    df_clean["GuV Stillhaltergeschäfte EUR"] = df_clean.apply(
        lambda x: c.convert(
            x["GuV Stillhaltergeschäfte"], 
            'USD', 'EUR', 
            date=x["Datum/Zeit"].date()), 
        axis=1) 

    # GuV Stillhaltergeschäfte + Gewinne Termingeschäfte
    zeile21 = df_clean["GuV Stillhaltergeschäfte EUR"].sum() + \
              df_clean.loc[df_clean["GuV Termingeschäfte EUR"] > 0, "GuV Termingeschäfte EUR"].sum()  
    
    # Verluste Termingeschäfte
    zeile24 = df_clean.loc[df_clean["GuV Termingeschäfte EUR"] < 0, "GuV Termingeschäfte EUR"].sum()
    
    gainloss = df_clean["Realisierter G&V"].sum()

    return df_clean, int(zeile21), int(-zeile24), int(gainloss)

def process_tasty_statement(csvfile) -> Tuple[pd.DataFrame, float, float]:
    df_tasty = pd.read_csv(uploaded_file)

    cols = ["TAX_YEAR", "SYMBOL", "SEC_SUBTYPE", "OPEN_DATE", "CLOSE_DATE", "CLOSE_EVENT", "QUANTITY", "LONG_SHORT_IND", "NO_WS_COST", "NO_WS_PROCEEDS", "NO_WS_GAINLOSS"]
    df_tasty = df_tasty[cols]

    for col in ["NO_WS_COST", "NO_WS_PROCEEDS", "NO_WS_GAINLOSS"]:
        df_tasty[col] = df_tasty[col].str.replace("$", "").astype(float)

    for col in ["OPEN_DATE", "CLOSE_DATE"]:
        df_tasty[col] = pd.to_datetime(df_tasty[col], format="%Y-%m-%d")

    df_tasty.loc[df_tasty["LONG_SHORT_IND"] == "L", "GuV Termingeschäfte"] = df_tasty["NO_WS_GAINLOSS"]
    df_tasty.loc[df_tasty["LONG_SHORT_IND"] == "S", "GuV Stillhaltergeschäfte open"] = df_tasty["NO_WS_PROCEEDS"]
    df_tasty.loc[df_tasty["LONG_SHORT_IND"] == "S", "GuV Stillhaltergeschäfte close"] = -df_tasty["NO_WS_COST"]        

    c = init_currencyconverter()

    df_tasty["GuV Termingeschäfte EUR"] = df_tasty.apply(
        lambda x: c.convert(
            x["GuV Termingeschäfte"], 
            'USD', 'EUR', 
            date=x["CLOSE_DATE"].date()), 
        axis=1)

    df_tasty["GuV Stillhaltergeschäfte open EUR"] = df_tasty.apply(
        lambda x: c.convert(
            x["GuV Stillhaltergeschäfte open"], 
            'USD', 'EUR', 
            date=x["OPEN_DATE"].date()), 
        axis=1)

    df_tasty["GuV Stillhaltergeschäfte close EUR"] = df_tasty.apply(
        lambda x: c.convert(
            x["GuV Stillhaltergeschäfte close"], 
            'USD', 'EUR', 
            date=x["CLOSE_DATE"].date()), 
        axis=1)

    # GuV Stillhaltergeschäfte + Gewinne Termingeschäfte
    zeile21 = df_tasty["GuV Stillhaltergeschäfte open EUR"].sum() + \
              df_tasty["GuV Stillhaltergeschäfte close EUR"].sum() + \
              df_tasty.loc[df_tasty["GuV Termingeschäfte EUR"] > 0, "GuV Termingeschäfte EUR"].sum()    

    # Verluste Termingeschäfte
    zeile24 = df_tasty.loc[df_tasty["GuV Termingeschäfte EUR"] < 0, "GuV Termingeschäfte EUR"].sum()

    gainloss = df_tasty["NO_WS_GAINLOSS"].sum()
    return df_tasty, int(zeile21), int(-zeile24), int(gainloss)


# APP
st.set_page_config(layout="wide")

# SIDEBAR
with st.sidebar:
    st.header("Stratton Oakmont Tax Dashboard")

    broker = st.selectbox(
        "Broker auswählen",
        ("IBKR", "TastyTrade"))    

    uploaded_file = st.file_uploader(
        "Statement hochladen")

    if uploaded_file is not None:
        if broker == "IBKR":
            df, zeile21, zeile24, gainloss = process_ibkr_statement(StringIO(uploaded_file.getvalue().decode("utf-8")))
        if broker == "TastyTrade":
            df, zeile21, zeile24, gainloss = process_tasty_statement(uploaded_file)
    
    
# PAGE
if uploaded_file is not None and not df.empty:
    st.header("Steuerliche Zuordnung der Transaktionen")

    if broker == "IBKR":
        st.caption("""BTO: Menge > 0 und Code O  
        STC: Menge < 0 und Code C  
        STO: Menge < 0 und Code O  
        BTC: Menge > 0 und Code C""")

        st.caption("""
        GuV Termingeschäfte: Wert aus Spalte 'Realisierter G&V' wenn 'Typ' = STC 
                   
        GuV Stillhaltergeschäfte (Vereinnahmung): Negativer Wert aus Spalte 'Basis' wenn 'Typ' = STO 
        
        GuV Stillhaltergeschäfte (Glattstellung): Differenz aus 'Realisierter G&V' und 'Basis' wenn 'Typ' = BTC 
        """)

        st.caption("""
        GuV aus Stillhaltergeschäften werden zum Zeitpunkt der Vereinnahmung bzw. Glattstellung tagesaktuell in EUR umgerechnet.  
        GuV aus Termingeschäften werden zum Zeitpunkt der Schließung des Geschäfts tagesaktuell in EUR umgerechnet.
        """)

    if broker == "TastyTrade":
        st.caption("""
        GuV Termingeschäfte: Wert aus Spalte 'NO_WS_GAINLOSS' wenn 'LONG_SHORT_IND' = L  
                   
        GuV Stillhaltergeschäfte (Vereinnahmung): Wert aus Spalte 'NO_WS_PROCEEDS' wenn 'LONG_SHORT_IND' = S 
                    
        GuV Stillhaltergeschäfte (Glattstellung): Wert aus Spalte 'NO_WS_COST' wenn 'LONG_SHORT_IND' = S  
        """)

        st.caption("""
        GuV aus Stillhaltergeschäften werden zum Zeitpunkt der Vereinnahmung bzw. Glattstellung tagesaktuell in EUR umgerechnet.  
        GuV aus Termingeschäften werden zum Zeitpunkt der Schließung des Geschäfts tagesaktuell in EUR umgerechnet.
        """)     

    st.dataframe(df, use_container_width=True)   

    if broker == "IBKR":
        zeile21_help = "Summe Spalte 'GuV Stillhaltergeschäfte EUR' + Summe aller positiven Werte aus Spalte 'GuV Termingeschäfte EUR'  "
        zeile24_help = "Summe aller negativen Werte aus Spalte 'GuV Termingeschäfte EUR'"
    if broker == "TastyTrade":
        zeile21_help = "Summe Spalte 'GuV Stillhaltergeschäfte open EUR' + Summe Spalte 'GuV Stillhaltergeschäfte close EUR' + Summe aller positiven Werte aus Spalte 'GuV Termingeschäfte EUR'  "
        zeile24_help = "Summe aller negativen Werte aus Spalte 'GuV Termingeschäfte EUR'"

    st.metric(
        label="Zeile 21: Stillhaltereinkünfte und Gewinne aus Termingeschäften (inkl. TAK)", 
        value=str(zeile21) + " €",
        help=zeile21_help)
    
    st.metric(
        label="Zeile 24: Verluste aus Termingeschäften (inkl. TAK)",
        value=str(zeile24) + " €",
        help=zeile24_help)  
    
    st.metric(
        label="Kontrolle (Summe Spalte NO_WS_GAINLOSS (Tasty) bzw. Realiserter G&V (IBKR))",
        value=str(gainloss) + " USD")  

    st.error("__Achtung:__ GuV aus Geschäften mit Aktien, Indizes, Futures und Devisen sowie Dividenden und Zinsen werden nicht berücksichtigt.")
   
