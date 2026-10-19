const HTML_ENDPOINT = "http://127.0.0.1:8000/api/v1/users/preview";

const fetchBtn = document.getElementById("fetch-btn");
const resultsDiv = document.getElementById("results");
const statusDiv = document.getElementById("status");

fetchBtn.addEventListener("click", async () => {
  statusDiv.textContent = "Connecting to API...";
  resultsDiv.innerHTML = "";

  try {
    const response = await fetch(HTML_ENDPOINT);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    // Read response payload as plain text/html
    const rawHtml = await response.text();

    statusDiv.textContent = "";
    resultsDiv.innerHTML = rawHtml;
  } catch (error) {
    statusDiv.textContent = "";
    resultsDiv.innerHTML = `<p style="color: #f85149;">Connection failed: ${error.message}</p>`;
  }
});

const HTML_ENDPOINT = "http://127.0.0.1:8000/api/v1/users/preview";

const fetchBtn = document.getElementById("fetch-btn");
const resultsDiv = document.getElementById("results");
const statusDiv = document.getElementById("status");

fetchBtn.addEventListener("click", async () => {
  statusDiv.textContent = "Connecting to API...";
  resultsDiv.innerHTML = "";

  try {
    const response = await fetch(HTML_ENDPOINT);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    // Read response payload as plain text/html
    const rawHtml = await response.text();

    statusDiv.textContent = "";
    resultsDiv.innerHTML = rawHtml;
  } catch (error) {
    statusDiv.textContent = "";
    resultsDiv.innerHTML = `<p style="color: #f85149;">Connection failed: ${error.message}</p>`;
  }
});