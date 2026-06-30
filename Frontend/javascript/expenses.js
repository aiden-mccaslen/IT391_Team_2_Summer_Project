function handleIn() {
    const test = document.getElementById("test").value;
    const testNum = parseFloat(test);
    const feedback = document.getElementById("feedback");
    if(isNaN(testNum) || !Number.isFinite(testNum)) {
        feedback.textContent = "Please enter a proper exepense value.";
        feedback.style.color = "red";
    } else {
        localStorage.setItem("testNum", testNum);
        feedback.textContent = "Saved value: " + testNum;
        feedback.style.color = "green";
    }
}

function clearIn() {
    document.getElementById("test").value="";
    document.getElementById("feedback").textContent="";
}