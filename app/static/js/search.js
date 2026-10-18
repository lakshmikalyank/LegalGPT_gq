document.addEventListener("DOMContentLoaded", () => {
    const searchBtn = document.getElementById("searchBtn");
    const city = document.getElementById("filterCity");
    const specialization = document.getElementById("filterSpecialization");
    const experience = document.getElementById("filterExperience");
    const results = document.getElementById("advocateResults");
    const resultsCount = document.getElementById("resultsCount");
    const template = document.getElementById("advocateCardTemplate");

    async function loadAdvocates() {
        const params = new URLSearchParams();

        if (city.value) params.append("city", city.value);
        if (specialization.value)
            params.append("specialization", specialization.value);
        if (experience.value)
            params.append("min_experience", experience.value);

        const response = await fetch("/api/advocates?" + params.toString());
        const data = await response.json();

        results.innerHTML = "";

        if (!data.success) return;

        resultsCount.textContent =
            `${data.advocates.length} advocate(s) found`;

        data.advocates.forEach(a => {
            const card = template.content.cloneNode(true);

            card.querySelector(".advocate-name").textContent = a.name;
            card.querySelector(".advocate-specialization").textContent = a.specialization;
            card.querySelector(".advocate-city").textContent = a.city;
            card.querySelector(".advocate-experience").textContent = a.experience_years;
            card.querySelector(".advocate-rating").textContent = a.rating ?? "-";
            card.querySelector(".advocate-phone").textContent = a.phone || "";
            card.querySelector(".advocate-email").textContent = a.email || "";

            results.appendChild(card);
        });
    }

    searchBtn.addEventListener("click", loadAdvocates);

    loadAdvocates();
});