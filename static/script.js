let teamsData = [];
let currentSort = { column: null, direction: 'asc' };

function fetchData() {
    fetch('/api/teams')
        .then(response => response.json())
        .then(data => {
            teamsData = data;
            renderTable();
            setupSortButtons();
        })
        .catch(error => {
            console.error('Error fetching teams:', error);
        });
}

function renderTable() {
    const tableBody = document.querySelector('#teamsTable tbody');
    tableBody.innerHTML = '';
    teamsData.forEach((team, index) => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${index + 1}</td>
            <td>${team.name}</td>
            <td>${team.conference}</td>
            <td>${team.wins}-${team.losses}</td>
            <td>${team.luck_adjusted_points_for ? team.luck_adjusted_points_for.toFixed(2) : 'N/A'}</td>
            <td>${team.strength_of_schedule || 'N/A'}</td>
            <td>${team.projected_wins ? team.projected_wins.toFixed(1) : 'N/A'}</td>
            <td>${team.playoff_chance ? team.playoff_chance.toFixed(1) + '%' : 'N/A'}</td>
            <td>${team.monke_score ? team.monke_score.toFixed(2) : 'N/A'}</td>
        `;
        tableBody.appendChild(row);
    });
}

function setupSortButtons() {
    const sortButtons = document.querySelectorAll('.sort-btn');
    sortButtons.forEach(button => {
        button.addEventListener('click', () => {
            const column = button.dataset.sort;
            sortTable(column);
        });
    });
}

function sortTable(column) {
    if (currentSort.column === column) {
        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
    } else {
        currentSort.column = column;
        currentSort.direction = 'asc';
    }

    teamsData.sort((a, b) => {
        let valueA, valueB;

        if (column === 'record') {
            valueA = a.wins / (a.wins + a.losses);
            valueB = b.wins / (b.wins + b.losses);
        } else {
            valueA = a[column];
            valueB = b[column];
        }

        if (valueA < valueB) return currentSort.direction === 'asc' ? -1 : 1;
        if (valueA > valueB) return currentSort.direction === 'asc' ? 1 : -1;
        return 0;
    });

    renderTable();
}

// Initial data fetch
fetchData();