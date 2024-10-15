document.addEventListener('DOMContentLoaded', () => {
    fetch('/api/teams')
        .then(response => response.json())
        .then(teams => {
            const tableBody = document.querySelector('#teams-table tbody');
            teams.forEach(team => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${team.name}</td>
                    <td>${team.conference}</td>
                    <td>${team.wins}-${team.losses}</td>
                    <td>${team.points_for.toFixed(2)}</td>
                    <td>${team.points_against.toFixed(2)}</td>
                    <td>${team.luck_adjusted_points_for.toFixed(2)}</td>
                    <td>${team.strength_of_schedule ? team.strength_of_schedule.toFixed(3) : 'N/A'}</td>
                `;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('Error fetching teams:', error));
});
