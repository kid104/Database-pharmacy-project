// ── Modal helpers ──────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id).classList.add('active');
  document.getElementById('modal-overlay').classList.add('active');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('active');
  document.getElementById('modal-overlay').classList.remove('active');
}

function closeAllModals() {
  document.querySelectorAll('.modal').forEach(m => m.classList.remove('active'));
  document.getElementById('modal-overlay').classList.remove('active');
}

// Close modals with Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeAllModals();
});

// ── Products page helpers ──────────────────────────────────────────────────

function editProduct(id, name, generic, form, strength, catId, rxOnly) {
  document.getElementById('edit_pid').value      = id;
  document.getElementById('edit_name').value     = name;
  document.getElementById('edit_generic').value  = generic;
  document.getElementById('edit_strength').value = strength;
  document.getElementById('edit_rx').checked     = rxOnly == 1;

  var formSel = document.getElementById('edit_form');
  if (formSel) {
    for (var i = 0; i < formSel.options.length; i++) {
      if (formSel.options[i].value === form) {
        formSel.selectedIndex = i;
        break;
      }
    }
  }

  var catSel = document.getElementById('edit_cat');
  if (catSel) {
    for (var j = 0; j < catSel.options.length; j++) {
      if (catSel.options[j].value == catId) {
        catSel.selectedIndex = j;
        break;
      }
    }
  }

  openModal('editModal');
}

function openBatchModal(productId, productName) {
  document.getElementById('batch_pid').value = productId;
  document.getElementById('batch_product_name').textContent = productName;
  openModal('batchModal');
}

// ── Patients page helpers ──────────────────────────────────────────────────

function editPatient(id, firstName, lastName, dob, gender, phone, medHistory, allergies) {
  document.getElementById('edit_patient_id').value      = id;
  document.getElementById('edit_first_name').value      = firstName;
  document.getElementById('edit_last_name').value       = lastName;
  document.getElementById('edit_dob').value             = dob;
  document.getElementById('edit_phone').value           = phone;
  document.getElementById('edit_medical_history').value = medHistory;
  document.getElementById('edit_allergies').value       = allergies;

  var genderSel = document.getElementById('edit_gender');
  if (genderSel) {
    for (var i = 0; i < genderSel.options.length; i++) {
      if (genderSel.options[i].value === gender) {
        genderSel.selectedIndex = i;
        break;
      }
    }
  }

  openModal('editModal');
}

// ── Move modals to body + auto-dismiss alerts ──────────────────────────────

document.addEventListener('DOMContentLoaded', function() {

  // Move every modal to document.body so it is never clipped by
  // overflow:hidden on a parent card or scroll container
  var modals = document.querySelectorAll('.modal');
  for (var i = 0; i < modals.length; i++) {
    document.body.appendChild(modals[i]);
  }

  // Auto-dismiss flash alerts after 4 seconds
  var alerts = document.querySelectorAll('.alert');
  for (var j = 0; j < alerts.length; j++) {
    (function(alert) {
      setTimeout(function() {
        alert.style.transition = 'opacity 0.5s';
        alert.style.opacity    = '0';
        setTimeout(function() { alert.remove(); }, 500);
      }, 4000);
    })(alerts[j]);
  }

});