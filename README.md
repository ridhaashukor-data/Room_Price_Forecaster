# How a Simple Forecasting Tool Can Support Hotel Revenue Strategy

This app is mainly useful as a **short-term forecasting tool** for revenue management. It helps estimate where occupancy is likely to end up for stay dates in the next 30 days, which can support better pricing and demand decisions. This project was built from my own product and business requirements. I defined the use case, workflow, and functional expectations, while the code itself was written by AI under my direction and iteration.

## Main features that matter most

### 1. Single-day forecast
This is probably the most directly useful feature for a revenue manager. It gives a forecast for one stay date based on current occupancy, along with demand signals and ADR guidance.

**Why it helps:**
- makes it easier to decide whether to push rate, hold rate, or stimulate demand
- can help avoid pricing too low on dates that are likely to fill
- can also help spot weak dates earlier
- input <img width="1531" height="929" alt="Single day input whole" src="https://github.com/user-attachments/assets/0a11785e-f024-4c5f-9507-b5bbcedbfb42" />

- output <img width="1317" height="614" alt="Single day output" src="https://github.com/user-attachments/assets/31654fd6-b40d-45ec-b28b-b10355c709a5" />


### 2. Bulk forecast
The Excel upload is useful when looking at multiple stay dates at once instead of checking them one by one.

**Why it helps:**
- gives a quicker view of the next few weeks
- helps spot strong dates and soft dates faster
- saves time compared with doing everything manually in spreadsheets
- input template
<img width="1854" height="770" alt="Bulk forecast input template" src="https://github.com/user-attachments/assets/64816024-3fdd-4988-81c4-64d236e75567" />


- output
<img width="528" height="790" alt="Bulk forecast output eg" src="https://github.com/user-attachments/assets/885053b7-5025-4b38-92e7-8441111c008e" />


### 3. Backtesting
This is important because it shows how accurate the forecast has been against historical results.

**Why it helps:**
- gives more confidence in using the tool
- shows where the forecast performs well and where it doesn’t
- makes it easier to improve forecasting over time instead of just guessing
- Backtest result for built-in data
<img width="1353" height="173" alt="Backtest result for built in data" src="https://github.com/user-attachments/assets/735d56a3-4c94-447d-8b71-a563d0fa4e72" />


- MAE (Mean Absolute Error) is the average size of forecasting error. It means the prediction is off by an average of X.XX percentage points. Lower is better.
- RMSE (Root Mean Squared Error) also measure error size, but it penalize large error heavily. Lower is better.
- MAPE (Mean Absolute Percentage Error) measure the deviation from true OCC. Lower is better.


### 4. Retraining / active dataset selection
The app can use built-in data or uploaded booking data, and the active dataset can be changed.

**Why it helps:**
- makes the forecast more tailored to the hotel’s own booking pattern
- useful if demand behavior changes over time
- gives more flexibility than using one fixed model forever

## Limitations to keep in mind

There are also some clear limitations.

- It only works for **up to 30 days out**, so it’s more useful for short-term tactics than long-term planning.
- It’s **not a full revenue management system**. It doesn’t include market pricing, competitor rate shopping, or full automation.
- The **bulk forecast is more occupancy-focused**, so it’s not doing full pricing recommendations across every row in the same way a full RMS might.
- The output is only as good as the data behind it. If the active dataset is old or not representative, the forecast may be less useful.
- It still needs human judgment, especially around unusual events, holidays, or sudden market changes. 

## Overall business value

Used in the right way, the app can help with:
- quicker pricing decisions
- better visibility on upcoming demand
- more consistent revenue review
- less manual spreadsheet work
- better balance between occupancy and ADR

This tool is best seen as a support system for revenue managers, especially for short-term decision-making. Its value is in giving a clearer view of where occupancy is likely to go and helping teams react earlier.
