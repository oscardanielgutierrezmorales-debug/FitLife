export const authRules = {
  usernameMin: 3,
  usernameMax: 80,
  passwordMin: 12,
  passwordMax: 128,
  usernamePattern: /^[A-Za-z0-9._-]+$/,
};

export function validateCredentials(values) {
  const errors = {};
  const username = typeof values?.username === "string" ? values.username.trim() : "";
  const password = typeof values?.password === "string" ? values.password : "";

  if (!username) errors.username = "Ingresa un nombre de usuario.";
  else if (username.length < authRules.usernameMin) errors.username = `El usuario debe tener al menos ${authRules.usernameMin} caracteres.`;
  else if (username.length > authRules.usernameMax) errors.username = `El usuario no puede superar los ${authRules.usernameMax} caracteres.`;
  else if (!authRules.usernamePattern.test(username)) errors.username = "El usuario solo puede contener letras, números, puntos, guiones y guiones bajos.";

  if (!password) errors.password = "Ingresa una contraseña.";
  else if (password.length < authRules.passwordMin) errors.password = `La contraseña debe tener al menos ${authRules.passwordMin} caracteres.`;
  else if (password.length > authRules.passwordMax) errors.password = `La contraseña no puede superar los ${authRules.passwordMax} caracteres.`;
  return errors;
}
